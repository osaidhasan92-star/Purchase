"""Native company and private tracking quote registers; no commercial posting."""

from functools import wraps
import re, secrets
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select, func, or_
from .app import db, User, app_document, body, problem, audit, validate_json, utcnow
from .permissions import allowed
from .erp import lock, dec, day, next_number
from .crm_register_store import Company, Quote, MODELS, MARKER, record, write_one
from .master_store import Lead, record as lead_record
from .crm_api import visible_leads
from .trade_store import version
from .trade_service import text
from .finance_api import paged, search_term

bp = Blueprint("crm_registers", __name__, url_prefix="/api/crm-registers")


class Command(db.Model):
    __tablename__ = "crm_register_command"
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    resource = db.Column(db.String(20), nullable=False)
    identity = db.Column(db.String(64), nullable=False)


def permit(key, action="view"):
    if key not in MODELS:
        problem("Unknown CRM register", 404)
    state = app_document().stored_data
    if not allowed(g.user, state, key, action):
        problem("CRM register permission required: " + action, 403)
    if not state.get(MARKER):
        problem("Run init-db and migrate-storage before using these registers", 503)


def scope(key):
    if key == "companies" or g.user.role == "Admin":
        return True
    actors = select(User.id).where(
        or_(User.id == g.user.id, User.manager_id == g.user.id)
    )
    return or_(Quote.created_by.in_(actors), Quote.owner_id.in_(actors))


def get(key, identity):
    if not isinstance(identity, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,64}", identity
    ):
        problem("Record not found", 404)
    row = db.session.scalar(
        select(MODELS[key]).where(MODELS[key].id == identity, scope(key))
    )
    if row is None:
        problem("Record not found", 404)
    return row


def output(key, row, detail=False):
    value = record(key, row)
    result = {**value, "version": version(value)}
    result.pop("salesHref", None)
    state = app_document().stored_data
    if (
        detail
        and key == "crmQuotes"
        and allowed(g.user, state, "leads")
        and allowed(g.user, state, "sales_quotations", "create")
        and db.session.scalar(
            select(Lead.id).where(Lead.id == row.lead_id, visible_leads())
        )
    ):
        from urllib.parse import urlencode

        result["salesHref"] = "erp.html?" + urlencode(
            dict(view="sales-quotations", leadId=row.lead_id)
        )
    return result


@bp.get("/lead-options")
def lead_options():
    permit("crmQuotes")
    if not allowed(g.user, app_document().stored_data, "leads"):
        problem("Leads view permission required", 403)
    q = select(Lead).where(visible_leads())
    term = search_term()
    if term:
        q = q.where(func.lower(Lead.name).like(term, escape="\\"))
    rows, meta = paged(q, [Lead.position, Lead.id])
    return jsonify(
        items=[
            dict(
                id=r[0].original_id,
                name=r[0].name
                or lead_record("leads", r[0]).get("companyName", "")
                or r[0].id,
            )
            for r in rows
        ],
        **meta
    )


@bp.get("/<key>")
def listing(key):
    permit(key)
    m = MODELS[key]
    q = select(m).where(scope(key))
    term = search_term()
    if term:
        columns = (
            (m.name, m.industry, m.contact, m.email)
            if key == "companies"
            else (m.name, m.number)
        )
        q = q.where(or_(*(func.lower(c).like(term, escape="\\") for c in columns)))
    if request.args.get("status"):
        q = q.where(m.status == request.args["status"])
    rows, meta = paged(q, [m.position, m.id])
    return jsonify(items=[output(key, r[0]) for r in rows], **meta)


@bp.get("/<key>/<identity>")
def detail(key, identity):
    permit(key)
    return jsonify(record=output(key, get(key, identity), detail=True))


@bp.post("/<key>")
@bp.patch("/<key>/<identity>")
def save(key, identity=None):
    permit(key)
    permit(key, "create" if identity is None else "edit")
    d = body()
    validate_json(d)
    fields = {
        "companies": {"name", "industry", "contact", "email", "phone", "status"},
        "crmQuotes": {
            "leadId",
            "amount",
            "currency",
            "quoteDate",
            "validUntil",
            "status",
        },
    }[key]
    if set(d) - fields - {"requestKey", "version"}:
        problem("Unknown or immutable CRM fields")
    request_key = d.get("requestKey", "")
    if not isinstance(request_key, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{8,100}", request_key
    ):
        problem("A unique requestKey is required")
    fingerprint = version(
        dict(
            key=key,
            id=identity,
            data={k: v for k, v in d.items() if k not in ("requestKey", "version")},
        )
    )
    lock()
    prior = db.session.get(Command, (g.user.id, request_key))
    if prior:
        if prior.fingerprint != fingerprint:
            problem("Request key was used for different details", 409)
        return jsonify(record=output(key, get(key, prior.identity)))
    row = get(key, identity) if identity else None
    old = record(key, row) if row else {}
    if row:
        if not d.get("version"):
            problem("Current version is required", 428)
        if d["version"] != version(old):
            problem("Record changed. Reload before saving.", 409)
    source = {**old, **d}
    normalized = {}
    if key == "companies":
        normalized = {
            f: text(source, f, limit=limit, required=f == "name")
            for f, limit in [
                ("name", 160),
                ("industry", 160),
                ("contact", 160),
                ("email", 254),
                ("phone", 80),
            ]
        }
        normalized["status"] = source.get("status", "Active")
        if normalized["status"] not in ("Active", "Inactive"):
            problem("Invalid company status")
        if normalized["email"] and not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized["email"]
        ):
            problem("Enter a valid email")
    else:
        if not allowed(g.user, app_document().stored_data, "leads"):
            problem("Leads view permission required", 403)
        lead = db.session.scalar(
            select(Lead).where(
                Lead.id == str(source.get("leadId", "")), visible_leads()
            )
        )
        if not lead:
            problem("Select an accessible lead")
        amount = dec(source.get("amount"), positive=True)
        currency = source.get("currency", "PKR")
        if not isinstance(currency, str) or (
            currency != "PKR" and (not row or currency != old.get("currency"))
        ):
            problem("New tracking quotes use PKR; historical currency can be retained")
        quote_date = day(source.get("quoteDate"))
        valid = day(source["validUntil"]) if source.get("validUntil") else ""
        if valid and valid < quote_date:
            problem("Validity must not precede quote date")
        status = source.get("status", "Draft")
        if status not in ("Draft", "Sent", "Accepted", "Rejected", "Expired"):
            problem("Invalid tracking status")
        normalized = dict(
            leadId=lead.original_id,
            companyName=lead.name or lead_record("leads", lead).get("companyName", ""),
            amount=float(amount),
            currency=currency,
            quoteDate=quote_date,
            validUntil=valid,
            status=status,
        )
    value = {**old, **normalized}
    if row is None:
        identity = "crm-" + secrets.token_hex(12)
        value.update(id=identity, createdBy=g.user.id, createdAt=utcnow())
        position = (db.session.scalar(select(func.min(MODELS[key].position))) or 0) - 1
        if key == "crmQuotes":
            number = next_number("CRM-Q")
            while db.session.scalar(
                select(Quote.id).where(Quote.number == number).limit(1)
            ):
                number = next_number("CRM-Q")
            value["quoteNo"] = number
    else:
        position = row.position
    row = write_one(key, value, position, row)
    db.session.add(
        Command(
            actor_id=g.user.id,
            request_key=request_key,
            fingerprint=fingerprint,
            resource=key,
            identity=identity,
        )
    )
    audit("Saved CRM register", {"resource": key, "id": identity})
    db.session.commit()
    return jsonify(record=output(key, row))
