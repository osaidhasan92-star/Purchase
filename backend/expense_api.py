"""Bounded expense claims with owner/manager/Finance scope and atomic commands."""

from functools import wraps
import re
from flask import Blueprint, g, jsonify, request, render_template_string
from sqlalchemy import select, func, or_
from .app import db, User, Attachment, app_document, body, problem, audit, validate_json
from .permissions import allowed
from .scope import finance_access
from .erp import (
    Expense,
    Account,
    dec,
    day,
    lock,
    next_number,
    post_entry,
    journal_pair,
    auto_reconcile,
)
from .trade_store import version
from .trade_service import text
from .finance_api import paged, search_term

bp = Blueprint("expenses", __name__, url_prefix="/api/expenses")


class Command(db.Model):
    __tablename__ = "expense_command"
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    identity = db.Column(db.Integer, nullable=False)


def permit(action="view"):
    if not allowed(g.user, app_document().stored_data, "expenses", action):
        problem("Expense permission denied: " + action, 403)


def read(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        permit()
        return fn(*a, **kw)

    return wrapped


def scope():
    if g.user.role == "Admin" or finance_access(g.user, app_document().stored_data):
        return True
    return Expense.owner_id.in_(
        select(User.id).where(or_(User.id == g.user.id, User.manager_id == g.user.id))
    )


def get(identity):
    if (
        isinstance(identity, bool)
        or not re.fullmatch(r"[1-9][0-9]{0,9}", str(identity))
        or int(identity) > 2147483647
    ):
        problem("Expense not found", 404)
    e = db.session.scalar(select(Expense).where(Expense.id == int(identity), scope()))
    if e is None:
        problem("Expense not found", 404)
    return e


def actions(e):
    state = app_document().stored_data
    if not allowed(g.user, state, "expenses", "edit"):
        return []
    approve = allowed(g.user, state, "expenses", "approve")
    if e.status == "Draft" and (approve or e.owner_id == g.user.id):
        return ["submit"]
    if e.status == "Submitted" and approve:
        return ["approve", "reject"]
    if e.status == "Approved" and approve and finance_access(g.user, state):
        return ["pay"]
    return []


def record(e):
    value = dict(
        id=e.id,
        number=e.number,
        employee=e.employee,
        ownerId=e.owner_id,
        description=e.description,
        account=e.account,
        amount=str(e.amount),
        tax=str(e.tax),
        total=str(e.amount + e.tax),
        date=e.date,
        status=e.status,
        attachmentId=e.attachment_id,
    )
    return {**value, "version": version(value), "actions": actions(e)}


@bp.get("/summary")
@read
def summary():
    rows = db.session.execute(
        select(Expense.status, func.count(), func.sum(Expense.amount + Expense.tax))
        .where(scope())
        .group_by(Expense.status)
    ).all()
    return jsonify(
        states={s: n for s, n, _ in rows}, amounts={s: str(v) for s, _, v in rows}
    )


@bp.get("/accounts")
@read
def accounts():
    rows, meta = paged(
        select(Account.code.label("id"), Account.name).where(Account.kind == "expense"),
        [Account.code],
    )
    return jsonify(items=[dict(r._mapping) for r in rows], **meta)


@bp.get("/claims")
@read
def claims():
    q = select(Expense).where(scope())
    term = search_term()
    if term:
        q = q.where(
            or_(
                *(
                    func.lower(c).like(term, escape="\\")
                    for c in (Expense.number, Expense.employee, Expense.description)
                )
            )
        )
    status = request.args.get("status")
    if status:
        if status not in ("Draft", "Submitted", "Approved", "Rejected", "Paid"):
            problem("Invalid claim status")
        q = q.where(Expense.status == status)
    start = day(request.args["from"]) if request.args.get("from") else None
    end = day(request.args["to"]) if request.args.get("to") else None
    if start and end and start > end:
        problem("Start date must precede end date")
    if start:
        q = q.where(Expense.date >= start)
    if end:
        q = q.where(Expense.date <= end)
    rows, meta = paged(q, [Expense.id.desc()])
    return jsonify(items=[record(r[0]) for r in rows], **meta)


@bp.get("/claims/<int:identity>")
@read
def detail(identity):
    return jsonify(record=record(get(identity)))


@bp.get("/claims/<int:identity>/print")
@read
def printable(identity):
    permit("export")
    e = record(get(identity))
    return render_template_string(
        """<!doctype html><html><head><title>{{e.number}}</title><style>body{font:16px sans-serif;max-width:800px;margin:40px auto}dt{font-weight:bold}dd{margin-bottom:16px}@media print{button{display:none}}</style></head><body><h1>Expense {{e.number}}</h1><dl>{% for k in ['employee','description','date','status','account','amount','tax','total'] %}<dt>{{k|title}}</dt><dd>{{e[k]}}</dd>{% endfor %}</dl><p>Currency PKR</p><button onclick="window.print()">Print / Save as PDF</button></body></html>""",
        e=e,
    )


def transition(e, action, data):
    """Same posting service used by both native and historical endpoints."""
    g.scope_creator = e.owner_id
    if action == "submit" and e.status == "Draft":
        e.status = "Submitted"
    elif action == "reject" and e.status == "Submitted":
        e.status = "Rejected"
    elif action == "approve" and e.status == "Submitted":
        post_entry(
            f"expense:{e.id}",
            e.number,
            [
                dict(account=e.account, debit=e.amount),
                dict(account="1300", debit=e.tax),
                dict(
                    account="2350",
                    credit=e.amount + e.tax,
                    partner="employee:" + e.employee,
                ),
            ],
            e.date,
        )
        e.status = "Approved"
    elif action == "pay" and e.status == "Approved":
        cash = str(data.get("account", "1010"))
        if cash not in ("1000", "1010"):
            problem("Choose cash or bank")
        entry = journal_pair(
            f"expense:{e.id}:payment",
            "Reimbursement " + e.number,
            "2350",
            cash,
            e.amount + e.tax,
            day(data.get("date")),
            partner="employee:" + e.employee,
        )
        auto_reconcile(f"expense:{e.id}", entry, "2350")
        e.status = "Paid"
    else:
        problem("Invalid expense transition", 409)


@bp.post("/commands/<action>")
def command(action):
    permit()
    fields = {
        "create": {"description", "account", "amount", "tax", "date", "attachmentId"},
        "submit": {"id", "version"},
        "approve": {"id", "version"},
        "reject": {"id", "version"},
        "pay": {"id", "version", "account", "date"},
    }
    if action not in fields:
        problem("Unknown expense command", 404)
    permit("create" if action == "create" else "edit")
    if action in ("approve", "reject", "pay"):
        permit("approve")
    if action == "pay" and not finance_access(g.user, app_document().stored_data):
        problem("Finance access required to reimburse expenses", 403)
    d = body()
    validate_json(d)
    if set(d) - fields[action] - {"requestKey"}:
        problem("Unknown or immutable expense fields")
    key = d.get("requestKey", "")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        problem("A unique requestKey of 8–100 characters is required")
    fingerprint = version(
        dict(
            action=action,
            data={k: v for k, v in d.items() if k not in ("requestKey", "version")},
        )
    )
    lock()
    receipt = db.session.get(Command, (g.user.id, key))
    if receipt:
        if receipt.fingerprint != fingerprint:
            problem("Request key was used for another command", 409)
        return jsonify(record=record(get(receipt.identity)))
    if action == "create":
        account = db.session.get(Account, str(d.get("account", "6105")))
        if not account or account.kind != "expense":
            problem("Select an expense account")
        amount = dec(d.get("amount"), positive=True)
        tax = dec(d.get("tax", 0))
        dec(amount + tax, positive=True)
        if tax < 0 or tax > amount:
            problem("Tax must be between zero and the expense amount")
        attachment = d.get("attachmentId") or None
        if attachment:
            if not isinstance(attachment, str):
                problem("Invalid receipt")
            file = db.session.get(Attachment, attachment)
            if not file or file.uploader_id != g.user.id or file.module != "expenses":
                problem("Select your uploaded expense receipt", 403)
        e = Expense(
            number=next_number("EXP"),
            employee=g.user.name,
            owner_id=g.user.id,
            description=text(d, "description", limit=500, required=True),
            account=account.code,
            amount=amount,
            tax=tax,
            date=day(d.get("date")),
            status="Draft",
            attachment_id=attachment,
            request_key="native-" + version([g.user.id, key]),
        )
        db.session.add(e)
        db.session.flush()
    else:
        e = get(d.get("id"))
        if not d.get("version"):
            problem("Current version is required", 428)
        if d["version"] != record(e)["version"]:
            problem("Claim changed. Reload before trying again.", 409)
        if action not in actions(e):
            problem("Action is not available for this claim", 403)
        transition(e, action, d)
    db.session.add(
        Command(
            actor_id=g.user.id, request_key=key, fingerprint=fingerprint, identity=e.id
        )
    )
    audit("Expense " + action, {"number": e.number, "status": e.status})
    db.session.commit()
    return jsonify(record=record(e))
