"""Invoice-linked return credits, settlement and refunds; atomic Finance commands."""

from decimal import Decimal
import re
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select, func, or_, update
from .app import db, Document, app_document, body, problem, audit, validate_json
from .permissions import allowed
from .erp import (
    JournalEntry,
    JournalLine,
    ERPProduct,
    StockMove,
    Reconciliation,
    dec,
    day,
    lock,
    next_number,
    post_entry,
    journal_pair,
    reconcile as ledger_reconcile,
    matched_amount,
)
from .trade_store import version
from . import trade_store as store
from .finance_api import paged

bp = Blueprint("credits", __name__, url_prefix="/api/credits")


class CreditNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False)
    kind = db.Column(db.String(12), nullable=False)
    invoice_id = db.Column(db.String(64), nullable=False, index=True)
    date = db.Column(db.String(10), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Draft")
    created_by = db.Column(db.String(64), nullable=False)
    amount = db.Column(db.Numeric(20, 2), nullable=False)
    tax = db.Column(db.Numeric(20, 2), nullable=False)
    journal_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"))
    lines = db.relationship("CreditLine", cascade="all, delete-orphan", lazy="selectin")


class CreditLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(
        db.Integer, db.ForeignKey("credit_note.id"), nullable=False, index=True
    )
    line_index = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Numeric(20, 4), nullable=False)
    amount = db.Column(db.Numeric(20, 2), nullable=False)
    tax = db.Column(db.Numeric(20, 2), nullable=False)
    stock_value = db.Column(db.Numeric(20, 2), nullable=False, default=0)
    return_id = db.Column(db.Integer, db.ForeignKey("stock_move.id"), index=True)


class CreditSettlement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(
        db.Integer, db.ForeignKey("credit_note.id"), nullable=False, index=True
    )
    kind = db.Column(db.String(12), nullable=False)
    invoice_id = db.Column(db.String(64), index=True)
    amount = db.Column(db.Numeric(20, 2), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    journal_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"))


class CreditCommand(db.Model):
    actor_id = db.Column(db.String(64), primary_key=True)
    request_key = db.Column(db.String(100), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    note_id = db.Column(db.Integer, db.ForeignKey("credit_note.id"), nullable=False)


def permit(action="view"):
    if not allowed(g.user, app_document().stored_data, "accounting", action):
        problem("Accounting permission denied: " + action, 403)


def resource(kind):
    if kind not in ("customer", "vendor"):
        problem("Choose customer or vendor credit")
    return "customerInvoices" if kind == "customer" else "invoices"


def invoice(kind, identity):
    from .trade_api import scoped

    row = scoped(resource(kind), str(identity))
    return store.record(resource(kind), row)


def amount_used(note):
    return dec(
        db.session.scalar(
            select(func.coalesce(func.sum(CreditSettlement.amount), 0)).where(
                CreditSettlement.note_id == note.id
            )
        )
    )


def record(note):
    inv = invoice(note.kind, note.invoice_id)
    used = amount_used(note)
    lines = [
        dict(
            lineIndex=l.line_index,
            quantity=str(l.quantity),
            amount=str(l.amount),
            tax=str(l.tax),
            returnId=l.return_id,
            returnNumber=(
                db.session.get(StockMove, l.return_id).number if l.return_id else None
            ),
            stockValue=str(l.stock_value),
        )
        for l in note.lines
    ]
    settlements = [
        dict(
            id=s.id,
            kind=s.kind,
            amount=str(s.amount),
            date=s.date,
            invoiceId=s.invoice_id,
            journalId=s.journal_id,
            journalSource=(
                db.session.get(JournalEntry, s.journal_id).source
                if s.journal_id
                else None
            ),
        )
        for s in db.session.scalars(
            select(CreditSettlement)
            .where(CreditSettlement.note_id == note.id)
            .order_by(CreditSettlement.id)
        )
    ]
    value = dict(
        id=note.id,
        number=note.number,
        kind=note.kind,
        invoiceId=note.invoice_id,
        invoiceNumber=inv.get("invoiceNo"),
        partner=inv.get("customerName" if note.kind == "customer" else "vendorName"),
        date=note.date,
        reason=note.reason,
        status=note.status,
        amount=str(note.amount),
        tax=str(note.tax),
        remaining=str(note.amount - used) if note.status == "Posted" else "0.00",
        journalId=note.journal_id,
        lines=lines,
        settlements=settlements,
    )
    value["version"] = version(value)
    actions = []
    if note.status == "Draft" and allowed(
        g.user, app_document().stored_data, "accounting", "edit"
    ):
        actions += ["submit", "cancel"]
    if note.status == "Pending Review" and allowed(
        g.user, app_document().stored_data, "accounting", "approve"
    ):
        actions += ["post", "reset", "cancel"]
    if (
        note.status == "Posted"
        and used < note.amount
        and allowed(g.user, app_document().stored_data, "accounting", "approve")
    ):
        actions += ["refund", "apply"]
    return {**value, "actions": actions}


def get(identity):
    note = db.session.get(CreditNote, identity)
    if note is None:
        problem("Credit note not found", 404)
    invoice(note.kind, note.invoice_id)
    return note


def source_line(inv, index):
    items = inv.get("items", [])
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or index < 0
        or index >= len(items)
    ):
        problem(
            "Choose an invoice line; historical amount-only invoices require accounting review"
        )
    return items[index]


def return_origin(move, kind, inv, line):
    if move is None or move.return_of is None:
        problem("Choose a validated stock return")
    original = db.session.get(StockMove, move.return_of)
    expected = "Customer Return" if kind == "customer" else "Vendor Return"
    if move.kind != expected or str(move.product_id) != str(line.get("productId")):
        problem("Return product or direction does not match the invoice")
    prefix, identity, position = (
        original.source.split(":")
        if original and len(original.source.split(":")) == 3
        else ("", "", "")
    )
    target = "deliveries" if kind == "customer" else "receipts"
    if prefix != target or not position.isdigit():
        problem("Return is not linked to a business receipt/delivery")
    parent = db.session.get(store.MODELS[target], identity)
    if not parent:
        problem("Original receipt/delivery not found")
    value = store.record(target, parent)
    if str(value.get("orderId" if kind == "customer" else "poId")) != str(
        inv.get("orderId" if kind == "customer" else "poId")
    ):
        problem("Return belongs to a different order")
    items = value.get("items", [])
    pos = int(position)
    if pos >= len(items) or int(items[pos].get("lineIndex", pos)) != int(
        line.get("lineIndex", 0)
    ):
        problem("Return belongs to a different order line")
    return original


@bp.get("")
def listing():
    permit()
    from .trade_api import visibility

    kind = request.args.get("kind", "customer")
    key = resource(kind)
    model = store.MODELS[key]
    query = select(CreditNote).where(
        CreditNote.kind == kind,
        CreditNote.invoice_id.in_(select(model.id).where(visibility(key))),
    )
    if not allowed(
        g.user,
        app_document().stored_data,
        "sales_invoices" if kind == "customer" else "invoices",
    ):
        problem("Invoice access required", 403)
    rows, meta = paged(query, [CreditNote.id.desc()])
    return jsonify(items=[record(r[0]) for r in rows], **meta)


@bp.get("/<int:identity>")
def details(identity):
    permit()
    return jsonify(record=record(get(identity)))


@bp.get("/source/<kind>/<identity>")
def source(kind, identity):
    permit()
    inv = invoice(kind, identity)
    if inv.get("status") not in ("Posted", "Approved", "Partially Paid", "Paid"):
        problem("Credit a posted invoice/bill")
    output = []
    for index, line in enumerate(inv.get("items", [])):
        used = db.session.scalar(
            select(func.coalesce(func.sum(CreditLine.quantity), 0))
            .join(CreditNote)
            .where(
                CreditNote.kind == kind,
                CreditNote.invoice_id == str(inv["id"]),
                CreditNote.status != "Cancelled",
                CreditLine.line_index == index,
            )
        ) or Decimal(0)
        returns = []
        product = db.session.get(ERPProduct, str(line.get("productId")))
        if product and product.kind == "stock":
            # Bound candidates by original order relationships, then validate each line.
            target = "deliveries" if kind == "customer" else "receipts"
            model = store.MODELS[target]
            ids = list(
                db.session.scalars(
                    select(model.id).where(
                        (model.order_id if kind == "customer" else model.po_id)
                        == str(inv.get("orderId" if kind == "customer" else "poId"))
                    )
                )
            )
            prefixes = [
                StockMove.source.like(
                    f"{target}:"
                    + str(i)
                    .replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                    + ":%",
                    escape="\\",
                )
                for i in ids
            ]
            originals = (
                list(db.session.scalars(select(StockMove.id).where(or_(*prefixes))))
                if prefixes
                else []
            )
            for move in db.session.scalars(
                select(StockMove).where(StockMove.return_of.in_(originals))
            ):
                try:
                    return_origin(move, kind, inv, line)
                except Exception as error:
                    from werkzeug.exceptions import HTTPException

                    if isinstance(error, HTTPException):
                        continue
                    raise
                allocated = db.session.scalar(
                    select(func.coalesce(func.sum(CreditLine.quantity), 0))
                    .join(CreditNote)
                    .where(
                        CreditLine.return_id == move.id,
                        CreditNote.status != "Cancelled",
                    )
                ) or Decimal(0)
                remaining = abs(move.quantity) - allocated
                if remaining > 0:
                    returns.append(
                        dict(
                            id=move.id,
                            number=move.number,
                            date=move.date,
                            remaining=str(remaining),
                        )
                    )
        output.append(
            dict(
                index=index,
                product=line.get("productName"),
                remaining=str(
                    max(Decimal(0), Decimal(str(line.get("quantity", 0))) - used)
                ),
                stock=bool(product and product.kind == "stock"),
                returns=returns,
            )
        )
    return jsonify(invoice=inv, lines=output)


def refresh_invoice(kind, identity, amount):
    from .trade_context import Context
    from .trade_service import recompute
    from .erp import sync_business

    key = resource(kind)
    context = Context(key, str(identity), {})
    row = next(v for v in context.state[key] if str(v["id"]) == str(identity))
    row["creditedAmount"] = float(
        dec(Decimal(str(row.get("creditedAmount", 0))) + amount)
    )
    recompute(context.state, key, row)
    context.persist()
    sync_business(context.original, context.state, "app")


def reconcile(debit, credit, amount):
    prior = getattr(g, "credit_settlement", False)
    g.credit_settlement = True
    try:
        ledger_reconcile(debit, credit, amount)
    finally:
        g.credit_settlement = prior


def apply(note, identity, amount, on_date):
    inv = invoice(note.kind, identity)
    origin = invoice(note.kind, note.invoice_id)
    partner_field = "customerId" if note.kind == "customer" else "vendorId"
    if inv.get(partner_field) != origin.get(partner_field):
        problem("Apply credit to the same customer/vendor only")
    if inv.get("status") not in ("Posted", "Approved", "Partially Paid"):
        problem("Choose an open posted invoice/bill")
    if on_date < str(inv.get("invoiceDate") or ""):
        problem("Settlement cannot precede the target invoice")
    if amount > Decimal(
        str(inv.get("balance", 0))
    ) or amount > note.amount - amount_used(note):
        problem("Credit exceeds the open invoice or available credit")
    account = "1100" if note.kind == "customer" else "2100"
    original = db.session.scalar(
        select(JournalEntry).where(
            JournalEntry.source == f"{resource(note.kind)}:{identity}"
        )
    )
    if not original:
        problem("Original invoice journal is missing")
    debit = next((l for l in original.lines if l.account == account), None)
    credit = next(
        l
        for l in db.session.get(JournalEntry, note.journal_id).lines
        if l.account == account
    )
    reconcile(
        debit if note.kind == "customer" else credit,
        credit if note.kind == "customer" else debit,
        amount,
    )
    db.session.add(
        CreditSettlement(
            note_id=note.id,
            kind="apply",
            invoice_id=str(identity),
            amount=amount,
            date=on_date,
        )
    )
    db.session.flush()
    refresh_invoice(note.kind, identity, amount)


@bp.post("/commands/<command>")
def command(command):
    permit()
    data = body()
    validate_json(data)
    fields = {
        "create": {"kind", "invoiceId", "date", "reason", "lines"},
        "submit": {"id", "version"},
        "cancel": {"id", "version"},
        "reset": {"id", "version"},
        "post": {"id", "version"},
        "refund": {"id", "version", "amount", "date", "account"},
        "apply": {"id", "version", "amount", "invoiceId", "date"},
    }
    if command not in fields or set(data) - fields[command] - {"requestKey"}:
        problem("Unknown credit command/fields")
    action = (
        "create"
        if command == "create"
        else "edit" if command in ("submit", "cancel") else "approve"
    )
    permit(action)
    token = data.get("requestKey", "")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", token):
        problem("A unique requestKey is required")
    fingerprint = version(
        dict(
            command=command,
            data={k: v for k, v in data.items() if k not in ("requestKey", "version")},
        )
    )
    lock()
    from .workflow_keys import revalidate_actor

    revalidate_actor()
    permit()
    permit(action)
    receipt = db.session.get(CreditCommand, (g.user.id, token))
    if receipt:
        if receipt.fingerprint != fingerprint:
            problem("Request key already used", 409)
        return jsonify(record=record(get(receipt.note_id)))
    if command == "create":
        kind = data.get("kind")
        inv = invoice(kind, data.get("invoiceId"))
        if inv.get("status") not in ("Posted", "Approved", "Partially Paid", "Paid"):
            problem("Credit a posted invoice/bill")
        date = day(data.get("date"))
        reason = data.get("reason", "")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
            problem("Enter a reason (1–500 characters)")
        if date < str(inv.get("invoiceDate") or ""):
            problem("Credit date cannot precede the invoice")
        items = data.get("lines")
        seen = set()
        lines = []
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            problem("Choose 1–100 invoice lines")
        for item in items:
            if not isinstance(item, dict) or set(item) - {
                "lineIndex",
                "quantity",
                "returnId",
            }:
                problem("Invalid credit line")
            index = item.get("lineIndex")
            line = source_line(inv, index)
            if index in seen:
                problem("Repeated invoice line")
            seen.add(index)
            qty = dec(item.get("quantity"), Decimal(".0001"), positive=True)
            prior = list(
                db.session.scalars(
                    select(CreditLine)
                    .join(CreditNote)
                    .where(
                        CreditNote.kind == kind,
                        CreditNote.invoice_id == str(inv["id"]),
                        CreditNote.status != "Cancelled",
                        CreditLine.line_index == index,
                    )
                )
            )
            used = sum((l.quantity for l in prior), Decimal(0))
            original = Decimal(str(line["quantity"]))
            if original <= 0:
                problem("Original invoice quantity requires accounting review")
            if qty + used > original:
                problem(
                    "Credit quantity exceeds the remaining original invoice quantity"
                )
            total = dec(line.get("total", 0))
            tax = dec(line.get("taxAmount", 0))
            value = dec(total * (used + qty) / original) - sum(
                (l.amount for l in prior), Decimal(0)
            )
            tax_value = dec(tax * (used + qty) / original) - sum(
                (l.tax for l in prior), Decimal(0)
            )
            product = db.session.get(ERPProduct, str(line.get("productId")))
            move = None
            stock_value = Decimal(0)
            if product is None:
                problem("Invoice product missing")
            if product.kind == "stock":
                return_id = item.get("returnId")
                if isinstance(return_id, bool) or not isinstance(return_id, int):
                    problem("Choose a stock return for each stock line")
                move = db.session.get(StockMove, return_id)
                return_origin(move, kind, inv, line)
                if date < move.date:
                    problem("Credit date cannot precede the stock return")
                allocations = list(
                    db.session.scalars(
                        select(CreditLine)
                        .join(CreditNote)
                        .where(
                            CreditLine.return_id == move.id,
                            CreditNote.status != "Cancelled",
                        )
                    )
                )
                allocated = sum((l.quantity for l in allocations), Decimal(0))
                if allocated + qty > abs(move.quantity):
                    problem("Stock return quantity has already been credited/reserved")
                stock_value = dec(
                    abs(move.value) * (allocated + qty) / abs(move.quantity)
                ) - sum((l.stock_value for l in allocations), Decimal(0))
            elif item.get("returnId") is not None:
                problem("Services do not use stock returns")
            lines.append(
                CreditLine(
                    line_index=index,
                    quantity=qty,
                    amount=value,
                    tax=tax_value,
                    return_id=move.id if move else None,
                    stock_value=stock_value,
                )
            )
        amount = sum((l.amount for l in lines), Decimal(0))
        tax = sum((l.tax for l in lines), Decimal(0))
        if amount <= 0 or tax < 0 or tax > amount:
            problem("Credit must have a positive valid amount")
        note = CreditNote(
            number=next_number("CN" if kind == "customer" else "VCN"),
            kind=kind,
            invoice_id=str(inv["id"]),
            date=date,
            reason=reason.strip(),
            status="Draft",
            created_by=g.user.id,
            amount=amount,
            tax=tax,
            lines=lines,
        )
        db.session.add(note)
        db.session.flush()
    else:
        identity = data.get("id")
        if isinstance(identity, bool) or not isinstance(identity, int):
            problem("Choose a credit note")
        note = get(identity)
        if data.get("version") != record(note)["version"]:
            problem("Credit changed; reload before continuing", 409)
        if command == "submit" and note.status == "Draft":
            note.status = "Pending Review"
        elif command == "reset" and note.status == "Pending Review":
            note.status = "Draft"
        elif command == "cancel" and note.status in ("Draft", "Pending Review"):
            if note.status == "Pending Review":
                permit("approve")
            note.status = "Cancelled"
        elif command == "post" and note.status == "Pending Review":
            inv = invoice(note.kind, note.invoice_id)
            customer = note.kind == "customer"
            partner = ("customer:" if customer else "vendor:") + str(
                inv.get("customerId" if customer else "vendorId")
            )
            account = "1100" if customer else "2100"
            net = note.amount - note.tax
            if customer:
                lines = [
                    dict(account="4100", debit=net),
                    dict(account="2200", debit=note.tax),
                    dict(account=account, credit=note.amount, partner=partner),
                ]
            else:
                stock = sum(
                    (l.stock_value for l in note.lines if l.return_id), Decimal(0)
                )
                stock_net = sum(
                    (l.amount - l.tax for l in note.lines if l.return_id), Decimal(0)
                )
                variance = stock - stock_net
                lines = [
                    dict(account=account, debit=note.amount, partner=partner),
                    dict(account="1300", credit=note.tax),
                    dict(account="2105", credit=stock),
                    dict(account="6105", credit=net - stock_net),
                ]
                if variance:
                    lines.append(
                        dict(
                            account="5105",
                            debit=max(variance, Decimal(0)),
                            credit=max(-variance, Decimal(0)),
                        )
                    )
            entry = post_entry("credit:" + str(note.id), note.number, lines, note.date)
            note.journal_id = entry.id
            note.status = "Posted"
            db.session.flush()
            amount = min(note.amount, Decimal(str(inv.get("balance", 0))))
            if amount > 0:
                apply(note, note.invoice_id, amount, note.date)
        elif command in ("apply", "refund") and note.status == "Posted":
            amount = dec(data.get("amount"), positive=True)
            on_date = day(data.get("date"))
            if on_date < note.date:
                problem("Settlement cannot precede the credit note")
            from .erp import check_period

            check_period(on_date)
            if amount > note.amount - amount_used(note):
                problem("Settlement exceeds the remaining credit")
            if command == "apply":
                apply(note, str(data.get("invoiceId")), amount, on_date)
            else:
                bank = data.get("account", "1010")
                if bank not in ("1000", "1010"):
                    problem("Choose bank or cash")
                inv = invoice(note.kind, note.invoice_id)
                customer = note.kind == "customer"
                account = "1100" if customer else "2100"
                partner = ("customer:" if customer else "vendor:") + str(
                    inv.get("customerId" if customer else "vendorId")
                )
                payment = journal_pair(
                    "credit-refund:" + version(dict(token=token, actor=g.user.id)),
                    note.number + " refund",
                    account if customer else bank,
                    bank if customer else account,
                    amount,
                    on_date,
                    partner,
                )
                original = next(
                    l
                    for l in db.session.get(JournalEntry, note.journal_id).lines
                    if l.account == account
                )
                refund = next(l for l in payment.lines if l.account == account)
                reconcile(
                    refund if customer else original,
                    original if customer else refund,
                    amount,
                )
                db.session.add(
                    CreditSettlement(
                        note_id=note.id,
                        kind="refund",
                        amount=amount,
                        date=on_date,
                        journal_id=payment.id,
                    )
                )
        else:
            problem("Action unavailable in current credit status", 409)
    db.session.flush()
    db.session.add(
        CreditCommand(
            actor_id=g.user.id,
            request_key=token,
            fingerprint=fingerprint,
            note_id=note.id,
        )
    )
    audit("Credit " + command, dict(number=note.number, amount=str(note.amount)))
    db.session.execute(
        update(Document)
        .where(Document.name == "app")
        .values(revision=Document.revision + 1)
    )
    db.session.commit()
    return jsonify(record=record(note))


def refresh_return_order(original):
    parts = original.source.split(":")
    if len(parts) != 3 or parts[0] not in ("deliveries", "receipts"):
        return
    from .trade_context import Context
    from .trade_service import recompute

    context = Context(parts[0], parts[1], {})
    row = next((v for v in context.state[parts[0]] if str(v["id"]) == parts[1]), None)
    if row:
        recompute(context.state, parts[0], row)
        from .warehouse_api import refresh
        refresh(context.state,parts[0],row)
        context.persist()
        db.session.execute(
            update(Document)
            .where(Document.name == "app")
            .values(revision=Document.revision + 1)
        )
