"""Native CRM resources. SQL visibility follows the existing creator/assignment policy."""

from datetime import date
from flask import g, jsonify, request
from sqlalchemy import select, or_, func
from .app import db, User, app_document, problem
from .master_api import bp, permit, save_record, output
from .master_store import Lead, Reminder, Customer, MODELS, record
from .permissions import allowed

STAGES = (
    "New",
    "Contacted",
    "Qualified",
    "Quotation Required",
    "Quotation in Preparation",
    "Quotation Pending Approval",
    "Quotation Approved",
    "Quotation Sent",
    "Closed Won",
    "Closed Lost",
)


def visible_leads():
    if g.user.role == "Admin":
        return True
    actors = select(User.id).where(
        or_(User.id == g.user.id, User.manager_id == g.user.id)
    )
    return or_(Lead.created_by.in_(actors), Lead.owner_id.in_(actors))


def visible_reminders():
    if g.user.role == "Admin":
        return True
    actors = select(User.id).where(
        or_(User.id == g.user.id, User.manager_id == g.user.id)
    )
    return or_(
        Reminder.created_by.in_(actors),
        Reminder.lead_id.in_(select(Lead.id).where(visible_leads())),
    )


def text(data, key, limit=160, default=""):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value.strip()) > limit:
        problem("Invalid " + key)
    return value.strip()


def iso(value):
    if value:
        try:
            date.fromisoformat(value)
        except ValueError:
            problem("Enter a valid date")
    return value


def normalize(key, data, old):
    editable = {
        "leads": {
            "customerId",
            "contact",
            "email",
            "stage",
            "value",
            "currency",
            "source",
            "expectedClose",
            "status",
            "notes",
            "ownerId",
        },
        "reminders": {"leadId", "type", "dueDate", "notes", "done"},
    }[key]
    if set(data) - editable - {"version", "requestKey"}:
        problem("Unknown CRM fields")
    source = {**(old or {}), **data}
    if key == "leads":
        customer = db.session.get(Customer, str(source.get("customerId", "")))
        if customer is None:
            problem("Select an existing customer")
        value = source.get("value", 0)
        import math

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1e12
        ):
            problem("Value must be a finite non-negative number")
        stage = source.get("stage", "New")
        if stage not in STAGES:
            problem("Invalid lead stage")
        if stage not in STAGES[:4] and stage != (old or {}).get("stage"):
            problem("Quotation stages and won/lost outcomes are set by Sales")
        result = dict(
            customerId=customer.original_id,
            customerName=customer.name,
            contact=text(source, "contact"),
            email=text(source, "email", 254),
            stage=stage,
            value=float(value),
            currency=text(source, "currency", 12, "PKR"),
            source=text(source, "source"),
            expectedClose=iso(text(source, "expectedClose", 10)),
            status=text(source, "status", 40, "Active"),
            notes=text(source, "notes", 10000),
            ownerId=source.get("ownerId") or (old or {}).get("ownerId") or g.user.id,
        )
        if result["status"] not in ("Active", "Inactive"):
            problem("Invalid lead status")
        if result["currency"] != "PKR":
            problem("This company uses PKR; foreign currency posting is not configured")
        if result["email"]:
            import re

            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result["email"]):
                problem("Enter a valid email address")
    else:
        lead = db.session.get(Lead, str(source.get("leadId", "")))
        if lead is None or not db.session.scalar(
            select(Lead.id).where(Lead.id == lead.id, visible_leads())
        ):
            problem("Lead not found", 404)
        done = source.get("done", False)
        if not isinstance(done, bool):
            problem("Done must be boolean")
        result = dict(
            leadId=lead.original_id,
            leadName=lead.name,
            type=text(source, "type", 40, "Call"),
            dueDate=iso(text(source, "dueDate", 10)),
            notes=text(source, "notes", 10000),
            done=done,
        )
        if not result["dueDate"]:
            problem("A due date is required")
        if result["type"] not in ("Call", "Email", "Meeting", "Follow-up"):
            problem("Invalid reminder type")
    return result


@bp.get("/crm/<key>")
def crm_list(key):
    if key not in ("leads", "reminders"):
        problem("Unknown CRM resource", 404)
    permit(key)
    try:
        page, size = int(request.args.get("page", "1")), int(
            request.args.get("pageSize", "25")
        )
    except ValueError:
        problem("Page and pageSize must be integers")
    if page < 1 or not 1 <= size <= 100:
        problem("Invalid pagination")
    search = request.args.get("search", "").strip()
    if len(search) > 160:
        problem("Search is too long")
    model = MODELS[key]
    query = select(model).where(
        visible_leads() if key == "leads" else visible_reminders()
    )
    if search:
        term = (
            "%"
            + search.casefold()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            + "%"
        )
        columns = [model.search_name, model.notes] + (
            [Lead.contact, Lead.stage, Lead.source]
            if key == "leads"
            else [Reminder.reminder_type]
        )
        query = query.where(or_(*(c.ilike(term, escape="\\") for c in columns)))
    total = db.session.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.session.scalars(
        query.order_by(model.position, model.id).offset((page - 1) * size).limit(size)
    )
    return jsonify(
        items=[output(record(key, r)) for r in rows],
        total=total,
        page=page,
        pageSize=size,
    )


@bp.get("/crm/assignees")
def crm_assignees():
    permit("leads")
    query = select(User).where(User.active == True)
    if g.user.role not in ("Admin", "CRM Manager"):
        query = query.where(or_(User.id == g.user.id, User.manager_id == g.user.id))
    users = db.session.scalars(query.order_by(User.name))
    return jsonify(
        items=[
            {"id": u.id, "name": u.name, "role": u.role, "managerId": u.manager_id}
            for u in users
            if u.id == g.user.id or u.role in ("Salesperson", "Sales Representative")
        ]
    )


@bp.route("/crm/<key>", methods=["POST"])
@bp.route("/crm/<key>/<identity>", methods=["PATCH"])
def crm_save(key, identity=None):
    if key not in ("leads", "reminders"):
        problem("Unknown CRM resource", 404)
    value, revision = save_record(
        key, identity, lambda data, old: normalize(key, data, old)
    )
    return jsonify(record=output(value), revision=revision)


@bp.get("/crm/summary")
def crm_summary():
    permit("leads")
    from .erp import day

    grouped = db.session.execute(
        select(Lead.stage, func.count(), func.coalesce(func.sum(Lead.value), 0))
        .where(visible_leads(), Lead.status != "Inactive")
        .group_by(Lead.stage)
    ).all()
    stages = [
        dict(stage=stage, count=count, value=float(value))
        for stage, count, value in grouped
    ]
    due = []
    if allowed(g.user, app_document().stored_data, "reminders"):
        due = db.session.scalars(
            select(Reminder)
            .where(
                visible_reminders(), Reminder.done == False, Reminder.due_date <= day()
            )
            .order_by(Reminder.due_date, Reminder.id)
            .limit(25)
        )
    return jsonify(
        stages=stages,
        active=sum(r["count"] for r in stages),
        pipeline=sum(
            r["value"]
            for r in stages
            if r["stage"] not in ("Closed Won", "Closed Lost")
        ),
        won=sum(r["value"] for r in stages if r["stage"] == "Closed Won"),
        due=[output(record("reminders", r)) for r in due],
    )
