"""Bounded SQL accounting workspace and versioned financial commands."""

from decimal import Decimal
from functools import wraps
import re
from flask import Blueprint, g, jsonify, request, render_template_string, make_response
from sqlalchemy import select, func, case, or_, and_
from .app import db, Document, app_document, body, problem, audit, validate_json
from .permissions import allowed, COLLECTIONS
from .erp import (
    Account,
    JournalEntry,
    JournalLine,
    Reconciliation,
    BankStatementLine,
    ERPControl,
    dec,
    day,
    lock,
    check_period,
    post_entry,
    journal_pair,
    reconcile,
)
from .trade_store import version
from .trade_service import text
from .scope import remember

bp = Blueprint("finance", __name__, url_prefix="/api/finance")


class Command(db.Model):
    __tablename__ = "finance_command"
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    resource = db.Column(db.String(30), nullable=False)
    identity = db.Column(db.String(64), nullable=False)


def permit(action="view"):
    if not allowed(g.user, app_document().stored_data, "accounting", action):
        problem("Accounting permission denied: " + action, 403)


def read(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        permit()
        return fn(*a, **kw)

    return wrapped


def paging():
    try:
        page = int(request.args.get("page", 1))
        size = int(request.args.get("pageSize", 25))
    except ValueError:
        problem("Pagination must use integers")
    if page < 1 or not 1 <= size <= 100:
        problem("Page must be positive and pageSize 1–100")
    return page, size


def paged(query, order):
    page, size = paging()
    count = db.session.scalar(
        select(func.count()).select_from(query.order_by(None).subquery())
    )
    return db.session.execute(
        query.order_by(*order).offset((page - 1) * size).limit(size)
    ).all(), dict(total=count, page=page, pageSize=size)


def search_term():
    text = request.args.get("search", "").strip()
    if len(text) > 160:
        problem("Search is too long")
    return (
        "%"
        + text.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        + "%"
        if text
        else None
    )


def dates():
    start = day(request.args["from"]) if request.args.get("from") else None
    end = day(request.args.get("to"))
    if start and start > end:
        problem("Start date must precede end date")
    return start, end


def matched():
    return (
        select(func.coalesce(func.sum(Reconciliation.amount), 0))
        .where(
            or_(
                Reconciliation.debit_line == JournalLine.id,
                Reconciliation.credit_line == JournalLine.id,
            )
        )
        .correlate(JournalLine)
        .scalar_subquery()
    )


def open_amount():
    return func.abs(JournalLine.debit - JournalLine.credit) - matched()


def get(model, identity):
    if model in (JournalEntry, JournalLine, BankStatementLine, ERPControl) and (
        isinstance(identity, bool)
        or not isinstance(identity, int)
        or not 0 < identity < 2147483648
    ):
        problem("Financial record not found", 404)
    obj = db.session.get(model, identity)
    if obj is None:
        problem("Financial record not found", 404)
    return obj


def line_record(line):
    amount = db.session.scalar(select(open_amount()).where(JournalLine.id == line.id))
    value = dict(
        id=line.id,
        entryId=line.entry_id,
        account=line.account,
        debit=str(line.debit),
        credit=str(line.credit),
        partner=line.partner,
        dueDate=line.due_date,
        openAmount=str(amount),
    )
    return {**value, "version": version(value)}


def entry_record(entry):
    lines = [line_record(l) for l in entry.lines]
    reversal = db.session.scalar(
        select(JournalEntry.id).where(JournalEntry.reversal_of == entry.id)
    )
    value = dict(
        id=entry.id,
        number=entry.number,
        source=entry.source,
        memo=entry.memo,
        date=entry.date,
        status=entry.status,
        reversalOf=entry.reversal_of,
        reversedBy=reversal,
        lines=lines,
    )
    actions = []
    if entry.source.startswith("manual:") and entry.status == "Draft":
        if allowed(g.user, app_document().stored_data, "accounting", "edit"):
            actions.append("edit")
        if allowed(g.user, app_document().stored_data, "accounting", "approve"):
            actions.append("post")
    if (
        entry.status == "Posted"
        and entry.source.startswith(("manual:", "transfer:"))
        and not reversal
        and allowed(g.user, app_document().stored_data, "accounting", "approve")
    ):
        actions.append("reverse")
    return {
        **value,
        "version": version(value),
        "actions": actions,
        "sourceLink": source_link(entry.source),
    }


def source_link(source):
    parts = source.split(":")
    if parts[0] == "stock":
        parts = parts[1:]
    if len(parts) < 2:
        return None
    key, identity = parts[:2]
    from . import trade_store, hr_store

    if key in trade_store.MODELS:
        if not all(
            allowed(g.user, app_document().stored_data, COLLECTIONS[key], a)
            for a in ("view", "export")
        ):
            return None
        from .trade_api import visibility

        model = trade_store.MODELS[key]
        if db.session.scalar(
            select(model.id).where(model.id == identity, visibility(key))
        ):
            return dict(
                label="Open source document",
                href="/api/trade/" + key + "/" + identity + "/print",
            )
    if (
        key == "expense"
        and re.fullmatch(r"[1-9][0-9]{0,9}", identity)
        and int(identity) <= 2147483647
        and all(
            allowed(g.user, app_document().stored_data, "expenses", a)
            for a in ("view", "export")
        )
    ):
        from .expense_api import scope
        from .erp import Expense

        if db.session.scalar(
            select(Expense.id).where(Expense.id == int(identity), scope())
        ):
            return dict(
                label="Open expense claim",
                href="/api/expenses/claims/" + identity + "/print",
            )
    if key == "payroll" and all(
        allowed(g.user, app_document().stored_data, "hr_payroll", a)
        for a in ("view", "export")
    ):
        from .hr_api import visibility

        if db.session.scalar(
            select(hr_store.Payroll.id).where(
                hr_store.Payroll.id == identity, visibility("payroll")
            )
        ):
            return dict(
                label="Open payslip",
                href="/api/hr/records/payroll/" + identity + "/print",
            )
    if (
        key == "mo"
        and all(
            allowed(g.user, app_document().stored_data, "manufacturing", a)
            for a in ("view", "export")
        )
        and re.fullmatch(r"[1-9][0-9]{0,9}", identity)
    ):
        from .erp import ManufacturingOrder

        if int(identity) < 2147483648 and db.session.get(
            ManufacturingOrder, int(identity)
        ):
            return dict(
                label="Open manufacturing order",
                href="/api/production/orders/" + identity + "/print",
            )
    return None


def statement_record(s):
    value = dict(
        id=s.id,
        date=s.date,
        description=s.description,
        account=s.account,
        amount=str(s.amount),
        matchedLine=s.matched_line,
    )
    return {**value, "version": version(value)}


def account_record(a):
    return dict(
        id=a.code,
        code=a.code,
        name=a.code + " · " + a.name,
        accountName=a.name,
        type=a.kind,
        reconcile=a.reconcile,
    )


def control_record():
    value = dict(date=get(ERPControl, 1).lock_date)
    return {**value, "version": version(value)}


@bp.get("/accounts")
@read
def accounts():
    query = select(Account)
    term = search_term()
    if term:
        query = query.where(
            or_(
                func.lower(Account.name).like(term, escape="\\"),
                Account.code.like(term, escape="\\"),
            )
        )
    kind = request.args.get("type")
    if kind:
        query = query.where(Account.kind == kind)
    if request.args.get("reconcile") == "true":
        query = query.where(Account.reconcile.is_(True))
    rows, meta = paged(query, [Account.code])
    return jsonify(items=[account_record(r[0]) for r in rows], **meta)


@bp.get("/entries")
@read
def entries():
    totals = (
        select(
            JournalLine.entry_id,
            func.sum(JournalLine.debit).label("debit"),
            func.sum(JournalLine.credit).label("credit"),
        )
        .group_by(JournalLine.entry_id)
        .subquery()
    )
    e = JournalEntry
    query = select(
        e.id,
        e.number,
        e.source,
        e.memo,
        e.date,
        e.status,
        totals.c.debit,
        totals.c.credit,
    ).outerjoin(totals, totals.c.entry_id == e.id)
    term = search_term()
    if term:
        query = query.where(
            or_(
                *(
                    func.lower(c).like(term, escape="\\")
                    for c in (e.number, e.source, e.memo)
                )
            )
        )
    if request.args.get("status"):
        query = query.where(e.status == request.args["status"])
    if request.args.get("from"):
        query = query.where(e.date >= day(request.args["from"]))
    if request.args.get("to"):
        query = query.where(e.date <= day(request.args["to"]))
    source = request.args.get("source", "")
    if source:
        if len(source) > 160:
            problem("Source filter too long")
        query = query.where(
            or_(
                e.source == source,
                e.source.startswith(source + ":", autoescape=True),
                e.source.startswith("stock:" + source + ":", autoescape=True),
            )
        )
    rows, meta = paged(query, [e.id.desc()])
    items = []
    for r in rows:
        item = dict(r._mapping)
        item.update(debit=str(item["debit"] or 0), credit=str(item["credit"] or 0))
        items.append(item)
    return jsonify(items=items, **meta)


@bp.get("/entries/<int:identity>")
@read
def entry(identity):
    return jsonify(record=entry_record(get(JournalEntry, identity)))


def report_totals(start, end):
    # Aggregate in SQL, not in a materialized journal/line graph.
    l, e = JournalLine, JournalEntry
    period = True if not start else e.date >= start
    sums = (
        select(
            l.account.label("code"),
            func.sum(l.debit).label("debit"),
            func.sum(l.credit).label("credit"),
            func.sum(case((period, l.debit), else_=0)).label("periodDebit"),
            func.sum(case((period, l.credit), else_=0)).label("periodCredit"),
        )
        .join(e)
        .where(e.status == "Posted", e.date <= end)
        .group_by(l.account)
        .subquery()
    )
    query = select(
        Account.code,
        Account.name,
        Account.kind.label("type"),
        *(
            func.coalesce(sums.c[k], 0).label(k)
            for k in ("debit", "credit", "periodDebit", "periodCredit")
        ),
    ).outerjoin(sums, sums.c.code == Account.code)
    return query.subquery()


def summary_values(t, start, end):
    balance = t.c.debit - t.c.credit
    period = t.c.periodDebit - t.c.periodCredit
    amount = lambda condition, expr: func.coalesce(
        func.sum(case((condition, expr), else_=0)), 0
    )
    values = (
        db.session.execute(
            select(
                amount(t.c.type == "asset", balance).label("assets"),
                amount(t.c.type == "liability", -balance).label("liabilities"),
                amount(t.c.type == "equity", -balance).label("equity"),
                amount(t.c.type.in_(["income", "expense"]), -balance).label(
                    "currentEarnings"
                ),
                amount(t.c.type.in_(["income", "expense"]), -period).label("profit"),
                amount(t.c.code.in_(["1000", "1010"]), balance).label("cashBank"),
                amount(t.c.code == "1100", balance).label("receivables"),
                amount(t.c.code == "2100", -balance).label("payables"),
                amount(t.c.code.in_(["1000", "1010"]), t.c.periodDebit).label("cashIn"),
                amount(t.c.code.in_(["1000", "1010"]), t.c.periodCredit).label(
                    "cashOut"
                ),
                func.coalesce(func.sum(t.c.periodDebit), 0).label("periodDebit"),
                func.coalesce(func.sum(t.c.periodCredit), 0).label("periodCredit"),
            )
        )
        .one()
        ._mapping
    )
    result = dict(values)
    result["balanceCheck"] = (
        result["assets"]
        - result["liabilities"]
        - result["equity"]
        - result["currentEarnings"]
    )
    result["openingCash"] = result["cashBank"] - result["cashIn"] + result["cashOut"]
    result["closingCash"] = result["cashBank"]
    return {
        **{k: str(v) for k, v in result.items()},
        "fromDate": start,
        "toDate": end,
        "currency": "PKR",
    }


@bp.get("/summary")
@read
def summary():
    start, end = dates()
    return jsonify(
        **summary_values(report_totals(start, end), start, end),
        periodLock=control_record(),
    )


@bp.get("/reports")
@read
def reports():
    start, end = dates()
    t = report_totals(start, end)
    summary = summary_values(t, start, end)
    query = select(t)
    kind = request.args.get("kind", "trial")
    if kind == "pnl":
        query = query.where(t.c.type.in_(["income", "expense"]))
    elif kind == "balance":
        query = query.where(t.c.type.in_(["asset", "liability", "equity"]))
    elif kind == "cash":
        query = query.where(t.c.code.in_(["1000", "1010"]))
    elif kind != "trial":
        problem("Unknown financial report")
    term = search_term()
    if term:
        query = query.where(
            or_(
                func.lower(t.c.name).like(term, escape="\\"),
                t.c.code.like(term, escape="\\"),
            )
        )
    rows, meta = paged(query, [t.c.code])
    items = []
    for r in rows:
        value = dict(r._mapping)
        value.update(
            balance=value["debit"] - value["credit"],
            opening=value["debit"]
            - value["credit"]
            - value["periodDebit"]
            + value["periodCredit"],
        )
        items.append(
            {k: str(v) if isinstance(v, Decimal) else v for k, v in value.items()}
        )
    return jsonify(items=items, summary=summary, kind=kind, **meta)


def ledger_query(open_only=False):
    l, e = JournalLine, JournalEntry
    start, end = dates()
    query = (
        select(
            l.id,
            l.entry_id.label("entryId"),
            e.number.label("entry"),
            e.source,
            e.memo,
            e.date,
            l.account,
            l.partner,
            l.due_date.label("dueDate"),
            l.debit,
            l.credit,
            open_amount().label("openAmount"),
        )
        .join(e)
        .where(e.status == "Posted", e.date <= end)
    )
    if start:
        query = query.where(e.date >= start)
    account = request.args.get("account")
    if account:
        query = query.where(l.account == account)
    partner = request.args.get("partner")
    if partner is not None:
        if len(partner) > 100:
            problem("Partner filter too long")
        query = query.where(l.partner == partner)
    term = search_term()
    if term:
        query = query.where(
            or_(
                *(
                    func.lower(c).like(term, escape="\\")
                    for c in (e.number, e.memo, l.partner, l.account)
                )
            )
        )
    if request.args.get("side") == "debit":
        query = query.where(l.debit > 0)
    if request.args.get("side") == "credit":
        query = query.where(l.credit > 0)
    if open_only:
        query = query.where(l.account.in_(["1100", "2100"]), open_amount() > 0)
    return query, start, end


def ledger_output(r):
    value = dict(r._mapping)
    return {
        k: (
            str(Decimal(str(v)).quantize(Decimal("0.01")))
            if k in ("debit", "credit", "openAmount", "amount") and v is not None
            else str(v) if isinstance(v, Decimal) else v
        )
        for k, v in value.items()
    }


@bp.get("/ledger")
@read
def ledger():
    query, start, end = ledger_query()
    rows, meta = paged(query, [JournalEntry.date, JournalLine.id])
    return jsonify(
        items=[ledger_output(r) for r in rows], fromDate=start, toDate=end, **meta
    )


@bp.get("/open-items")
@read
def open_items():
    query, start, end = ledger_query(True)
    rows, meta = paged(query, [JournalEntry.date, JournalLine.id])
    items = []
    from datetime import date

    for r in rows:
        v = ledger_output(r)
        due = v["dueDate"] or v["date"]
        overdue = (date.fromisoformat(end) - date.fromisoformat(due)).days
        v["bucket"] = (
            "Not due"
            if overdue <= 0
            else (
                "1–30"
                if overdue <= 30
                else "31–60" if overdue <= 60 else "61–90" if overdue <= 90 else "90+"
            )
        )
        v["version"] = line_record(get(JournalLine, v["id"]))["version"]
        v["name"] = (
            str(v["id"])
            + " · "
            + v["entry"]
            + " · "
            + v["partner"]
            + " · PKR "
            + str(v["openAmount"])
        )
        items.append(v)
    return jsonify(
        items=items,
        asOf=end,
        settlements="Current reconciliation state; not historical settlement balances",
        **meta,
    )


@bp.get("/lines/<int:identity>")
@read
def line(identity):
    return jsonify(record=line_record(get(JournalLine, identity)))


@bp.get("/statements")
@read
def statements():
    query = select(BankStatementLine)
    term = search_term()
    s = BankStatementLine
    if term:
        query = query.where(func.lower(s.description).like(term, escape="\\"))
    if request.args.get("account"):
        query = query.where(s.account == request.args["account"])
    if request.args.get("status") == "Unmatched":
        query = query.where(s.matched_line.is_(None))
    if request.args.get("status") == "Matched":
        query = query.where(s.matched_line.is_not(None))
    rows, meta = paged(query, [s.id.desc()])
    return jsonify(items=[statement_record(r[0]) for r in rows], **meta)


@bp.get("/statements/<int:identity>/candidates")
@read
def bank_candidates(identity):
    statement = get(BankStatementLine, identity)
    l, e = JournalLine, JournalEntry
    query = (
        select(
            l.id,
            e.number.label("entry"),
            e.memo,
            e.date,
            l.account,
            (l.debit - l.credit).label("amount"),
        )
        .join(e)
        .where(
            e.status == "Posted",
            l.account == statement.account,
            l.debit - l.credit == statement.amount,
            ~select(BankStatementLine.id)
            .where(BankStatementLine.matched_line == l.id)
            .exists(),
        )
    )
    term = search_term()
    if term:
        query = query.where(
            or_(
                func.lower(e.number).like(term, escape="\\"),
                func.lower(e.memo).like(term, escape="\\"),
            )
        )
    rows, meta = paged(query, [e.date, l.id])
    items = []
    for r in rows:
        v = ledger_output(r)
        v.update(
            name=v["entry"] + " · " + v["date"] + " · " + v["memo"],
            version=line_record(get(l, v["id"]))["version"],
        )
        items.append(v)
    return jsonify(items=items, **meta)


@bp.get("/period-lock")
@read
def period_lock():
    return jsonify(record=control_record(), canChange=g.user.role == "Admin")


def require_version(data, expected, field="version"):
    if not data.get(field):
        problem("Current " + field + " is required", 428)
    if data[field] != expected:
        problem("Financial record changed. Reload before trying again.", 409)


def money(value, positive=False):
    return dec(value, positive=positive)


def parse_lines(data):
    rows = data.get("lines")
    if not isinstance(rows, list) or not 2 <= len(rows) <= 100:
        problem("Provide 2–100 journal lines")
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) - {
            "account",
            "debit",
            "credit",
            "partner",
            "dueDate",
        }:
            problem("Invalid journal line fields")
        account = str(row.get("account", ""))
        get(Account, account)
        debit = money(row.get("debit", 0))
        credit = money(row.get("credit", 0))
        if debit < 0 or credit < 0 or (debit and credit) or not (debit or credit):
            problem("Each line needs a positive debit OR credit")
        partner = text(row, "partner", limit=100)
        if row.get("dueDate") is not None and not isinstance(row["dueDate"], str):
            problem("Due date must use YYYY-MM-DD")
        due = day(row["dueDate"]) if row.get("dueDate") else None
        result.append(
            dict(
                account=account,
                debit=debit,
                credit=credit,
                partner=partner,
                dueDate=due,
            )
        )
    if sum(l["debit"] for l in result) != sum(l["credit"] for l in result):
        problem("Debits and credits must balance exactly")
    return result


def result_for(resource, identity):
    if resource == "entries":
        return entry_record(get(JournalEntry, int(identity)))
    if resource == "statements":
        return statement_record(get(BankStatementLine, int(identity)))
    if resource == "accounts":
        return account_record(get(Account, identity))
    if resource == "period-lock":
        return control_record()
    return line_record(get(JournalLine, int(identity)))


@bp.post("/commands/<command>")
def command(command):
    permit()
    data = body()
    validate_json(data)
    fields = {
        "account": {"code", "name", "type", "reconcile"},
        "journal": {"memo", "date", "lines"},
        "edit-journal": {"id", "memo", "date", "lines", "version"},
        "post": {"id", "version"},
        "reverse": {"id", "version", "date"},
        "transfer": {"fromAccount", "toAccount", "amount", "date"},
        "statement": {"date", "description", "account", "amount"},
        "match-bank": {"id", "version", "lineId", "lineVersion"},
        "reconcile": {
            "debitLine",
            "creditLine",
            "debitVersion",
            "creditVersion",
            "amount",
        },
        "period-lock": {"date", "version"},
    }
    if command not in fields:
        problem("Unknown finance command", 404)
    if set(data) - fields[command] - {"requestKey"}:
        problem("Unknown or immutable finance fields")
    action = (
        "edit"
        if command == "edit-journal"
        else (
            "approve"
            if command in ("post", "reverse", "match-bank", "reconcile", "period-lock")
            else "create"
        )
    )
    permit(action)
    if command == "transfer":
        permit("approve")
    if command == "period-lock" and g.user.role != "Admin":
        problem("Only administrators change accounting locks", 403)
    key = data.get("requestKey", "")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        problem("A unique requestKey of 8–100 characters is required")
    for date_field in ("date",):
        if (
            date_field in data
            and data[date_field] is not None
            and not isinstance(data[date_field], str)
        ):
            problem("Date must use YYYY-MM-DD")
    fingerprint = version(
        dict(
            command=command,
            data={
                k: v
                for k, v in data.items()
                if k
                not in (
                    "requestKey",
                    "version",
                    "lineVersion",
                    "debitVersion",
                    "creditVersion",
                )
            },
        )
    )
    lock()
    receipt = db.session.get(Command, (g.user.id, key))
    if receipt:
        if receipt.fingerprint != fingerprint:
            problem("Request key was already used for another command", 409)
        return jsonify(record=result_for(receipt.resource, receipt.identity))
    resource = "entries"
    identity = None
    entry = None
    if command == "account":
        code = data.get("code", "")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{4,8}", code):
            problem("Account code must be 4–8 digits")
        if data.get("type") not in (
            "asset",
            "liability",
            "equity",
            "income",
            "expense",
        ):
            problem("Invalid account type")
        if not isinstance(data.get("reconcile", False), bool):
            problem("Reconcile must be true or false")
        if db.session.get(Account, code):
            problem("Account code already exists", 409)
        a = Account(
            code=code,
            name=text(data, "name", limit=160, required=True),
            kind=data["type"],
            reconcile=data.get("reconcile", False),
        )
        db.session.add(a)
        db.session.flush()
        remember(a)
        resource = "accounts"
        identity = code
    elif command in ("journal", "edit-journal"):
        lines = parse_lines(data)
        memo = text(data, "memo", limit=500, required=True)
        value_date = day(data.get("date"))
        check_period(value_date)
        if command == "journal":
            entry = post_entry(
                "manual:native:" + version(dict(actor=g.user.id, key=key)),
                memo,
                lines,
                value_date,
                draft=True,
            )
        else:
            entry = get(JournalEntry, identity_int(data, "id"))
            require_version(data, entry_record(entry)["version"])
            if entry.status != "Draft" or not entry.source.startswith("manual:"):
                problem("Only draft manual journals can change", 409)
            entry.memo = memo
            entry.date = value_date
            entry.lines = [
                JournalLine(
                    account=l["account"],
                    debit=l["debit"],
                    credit=l["credit"],
                    partner=l["partner"],
                    due_date=l["dueDate"],
                )
                for l in lines
            ]
    elif command in ("post", "reverse"):
        entry = get(JournalEntry, identity_int(data, "id"))
        require_version(data, entry_record(entry)["version"])
        if command == "post":
            if entry.status != "Draft" or not entry.source.startswith("manual:"):
                problem("Only draft manual journals can post", 409)
            check_period(entry.date)
            entry.status = "Posted"
        else:
            if (
                entry.status != "Posted"
                or not entry.source.startswith(("manual:", "transfer:"))
                or db.session.scalar(
                    select(JournalEntry.id).where(JournalEntry.reversal_of == entry.id)
                )
            ):
                problem(
                    "Only unreversed posted manual journals/transfers may reverse", 409
                )
            ids = [l.id for l in entry.lines]
            if db.session.scalar(
                select(Reconciliation.id)
                .where(
                    or_(
                        Reconciliation.debit_line.in_(ids),
                        Reconciliation.credit_line.in_(ids),
                    )
                )
                .limit(1)
            ) or db.session.scalar(
                select(BankStatementLine.id)
                .where(BankStatementLine.matched_line.in_(ids))
                .limit(1)
            ):
                problem(
                    "Matched journal items require accounting review before reversal",
                    409,
                )
            original = entry
            entry = post_entry(
                "reversal:" + str(original.id),
                "Reversal of " + original.number,
                [
                    dict(
                        account=l.account,
                        debit=l.credit,
                        credit=l.debit,
                        partner=l.partner,
                        dueDate=l.due_date,
                    )
                    for l in original.lines
                ],
                day(data.get("date")),
            )
            entry.reversal_of = original.id
    elif command == "transfer":
        source, target = data.get("fromAccount"), data.get("toAccount")
        if (
            source not in ("1000", "1010")
            or target not in ("1000", "1010")
            or source == target
        ):
            problem("Choose different cash/bank accounts")
        entry = journal_pair(
            "transfer:native:" + version(dict(actor=g.user.id, key=key)),
            "Internal bank/cash transfer",
            target,
            source,
            money(data.get("amount"), True),
            day(data.get("date")),
        )
    elif command == "statement":
        account = data.get("account")
        if account not in ("1000", "1010"):
            problem("Choose cash or bank")
        amount = money(data.get("amount"))
        if not amount:
            problem("Statement amount cannot be zero")
        s = BankStatementLine(
            date=day(data.get("date")),
            description=text(data, "description", limit=300, required=True),
            account=account,
            amount=amount,
            request_key="native:" + g.user.id + ":" + key,
        )
        # Existing request_key column is 100 chars; use the fixed-size fingerprint as the storage key.
        s.request_key = "native:" + version(dict(actor=g.user.id, key=key))
        db.session.add(s)
        db.session.flush()
        remember(s)
        resource = "statements"
        identity = s.id
    elif command == "match-bank":
        s = get(BankStatementLine, identity_int(data, "id"))
        line = get(JournalLine, identity_int(data, "lineId"))
        require_version(data, statement_record(s)["version"])
        require_version(data, line_record(line)["version"], "lineVersion")
        if (
            s.matched_line
            or line.entry.status != "Posted"
            or line.account != s.account
            or line.debit - line.credit != s.amount
        ):
            problem(
                "Match an unmatched statement to a posted item with the same account and signed amount",
                409,
            )
        if db.session.scalar(
            select(BankStatementLine.id).where(
                BankStatementLine.matched_line == line.id
            )
        ):
            problem("Journal item already matched", 409)
        s.matched_line = line.id
        resource = "statements"
        identity = s.id
    elif command == "reconcile":
        debit = get(JournalLine, identity_int(data, "debitLine"))
        credit = get(JournalLine, identity_int(data, "creditLine"))
        require_version(data, line_record(debit)["version"], "debitVersion")
        require_version(data, line_record(credit)["version"], "creditVersion")
        reconcile(debit, credit, money(data.get("amount"), True))
        resource = "lines"
        identity = debit.id
    elif command == "period-lock":
        require_version(data, control_record()["version"])
        get(ERPControl, 1).lock_date = day(data["date"]) if data.get("date") else None
        resource = "period-lock"
        identity = "1"
    if entry is not None:
        db.session.flush()
        identity = entry.id
    db.session.flush()
    db.session.add(
        Command(
            actor_id=g.user.id,
            request_key=key,
            fingerprint=fingerprint,
            resource=resource,
            identity=str(identity),
        )
    )
    audit("Finance " + command, dict(resource=resource, recordId=identity))
    db.session.commit()
    return jsonify(record=result_for(resource, str(identity)))


def identity_int(data, field):
    v = data.get(field)
    if (
        isinstance(v, bool)
        or not isinstance(v, (str, int))
        or not re.fullmatch(r"[1-9][0-9]{0,17}", str(v))
    ):
        problem("Invalid " + field)
    return int(v)


@bp.get("/entries/<int:identity>/print")
@read
def print_entry(identity):
    permit("export")
    entry = entry_record(get(JournalEntry, identity))
    response = make_response(
        render_template_string(
            """<!doctype html><html lang="en"><meta charset="utf-8"><title>{{r.number}}</title><style>body{font:14px Arial;margin:36px;color:#172338}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #ddd;text-align:left}@media print{button{display:none}}</style><h1>{{company.get('name','Company')}}</h1><h2>Journal {{r.number}} · {{r.status}}</h2><p>{{r.date}} · {{r.memo}}</p><p>Source: {{r.source}}</p><table><tr><th>Account</th><th>Partner</th><th>Due</th><th>Debit PKR</th><th>Credit PKR</th></tr>{% for l in r.lines %}<tr><td>{{l.account}}</td><td>{{l.partner}}</td><td>{{l.dueDate or ''}}</td><td>{{l.debit}}</td><td>{{l.credit}}</td></tr>{% endfor %}</table><p>Pakistan · PKR</p><button onclick="window.print()">Print / Save as PDF</button></html>""",
            r=entry,
            company=app_document().stored_data.get("company", {}),
        )
    )
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@bp.get("/ledger/export")
@read
def export():
    permit("export")
    import csv, io

    query, start, end = ledger_query()
    rows, meta = paged(query, [JournalEntry.date, JournalLine.id])
    fields = ["date", "entry", "account", "memo", "partner", "debit", "credit"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields)
    for r in rows:
        v = ledger_output(r)
        cells = []
        for field in fields:
            cell = str(v.get(field, ""))
            if cell.lstrip().startswith(("=", "+", "-", "@")):
                cell = "'" + cell
            cells.append(cell)
        writer.writerow(cells)
    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="general-ledger-pkr-page-{meta["page"]}.csv"'
    )
    return response
