"""Order fulfillment closure and permission-aware return/credit progress."""

from decimal import Decimal
from flask import g
from sqlalchemy import select
from .app import db, app_document, problem
from .permissions import allowed, COLLECTIONS
from . import trade_store as store


def gross(state, order, index, customer):
    total = Decimal(0)
    for document in state.get("deliveries" if customer else "receipts", []):
        if str(document.get("orderId" if customer else "poId")) != str(order["id"]):
            continue
        if customer and document.get("status") != "Delivered":
            continue
        for position, line in enumerate(document.get("items", [])):
            if int(line.get("lineIndex", position)) == index:
                total += Decimal(
                    str(line.get("deliveredQty" if customer else "acceptedQty", 0))
                )
    return total


def close(state, key, order, data):
    from .trade_service import dispatched, received, billed_quantity, utcnow, text

    customer = key == "salesOrders"
    if order.get("status") in ("Draft", "Pending Approval", "Cancelled", "Closed"):
        problem("Close only an approved open order", 409)
    reason = text(data, "reason", limit=500, required=True)
    if customer and any(
        str(d.get("orderId")) == str(order["id"]) and d.get("status") == "Pending"
        for d in state.get("deliveries", [])
    ):
        problem("Validate or cancel pending deliveries before closing the remainder")
    invoice_key = "customerInvoices" if customer else "invoices"
    if any(
        str(inv.get("orderId" if customer else "poId")) == str(order["id"])
        and inv.get("status") not in ("Cancelled", "Exception")
        and not inv.get("items")
        for inv in state.get(invoice_key, [])
    ):
        problem(
            "Historical invoice lines require Finance review before closing the remainder"
        )
    closure = []
    activity = False
    for index, line in enumerate(order.get("items", [])):
        done = (
            dispatched(state, order, index)
            if customer
            else received(state, order, index)
        )
        activity = activity or gross(state, order, index, customer) > 0
        if not customer:
            activity = activity or any(
                str(r.get("poId")) == str(order["id"])
                and any(
                    Decimal(str(i.get("receivedQty", 0))) > 0
                    for i in r.get("items", [])
                )
                for r in state.get("receipts", [])
            )
        if billed_quantity(state, order, index, customer) > done:
            problem(
                "Resolve excess invoiced quantities with Finance, or cancel excess drafts, before closing"
            )
        closure.append(
            dict(
                lineIndex=index,
                quantity=float(max(Decimal(0), Decimal(str(line["quantity"])) - done)),
                fulfilled=float(done),
            )
        )
    if not activity or not any(line["quantity"] > 0 for line in closure):
        problem(
            "Close Remaining Quantity requires a partially fulfilled or returned order"
        )
    order.update(
        status="Closed",
        fulfillmentClosed=True,
        closedRemainder=closure,
        closeReason=reason,
        closedAt=utcnow(),
        closedBy=g.user.id,
        closedByName=g.user.name,
    )


def progress(state, order, index, customer):
    from .trade_service import dispatched, received, billed_quantity

    done = (
        dispatched(state, order, index) if customer else received(state, order, index)
    )
    fulfilled = gross(state, order, index, customer)
    invoice_key = "customerInvoices" if customer else "invoices"
    visible_finance = allowed(
        g.user, app_document().stored_data, COLLECTIONS[invoice_key]
    )
    values = dict(
        fulfilled=float(fulfilled),
        returned=float(max(Decimal(0), fulfilled - done)),
        netFulfilled=float(done),
        closedRemaining=next(
            (
                line["quantity"]
                for line in order.get("closedRemainder", [])
                if line["lineIndex"] == index
            ),
            0,
        ),
    )
    if not customer:
        inspected = sum(
            (
                Decimal(str(item.get("receivedQty", 0)))
                for receipt in state.get("receipts", [])
                if str(receipt.get("poId")) == str(order["id"])
                for position, item in enumerate(receipt.get("items", []))
                if int(item.get("lineIndex", position)) == index
            ),
            Decimal(0),
        )
        values.update(
            receivedForInspection=float(inspected),
            rejected=float(max(Decimal(0), inspected - fulfilled)),
        )
    if visible_finance:
        billed = billed_quantity(state, order, index, customer)
        invoiced = sum(
            (
                Decimal(str(item.get("quantity", 0)))
                for inv in state.get(invoice_key, [])
                if str(inv.get("orderId" if customer else "poId")) == str(order["id"])
                and inv.get("status") not in ("Cancelled", "Exception")
                for position, item in enumerate(inv.get("items", []))
                if int(item.get("lineIndex", position)) == index
            ),
            Decimal(0),
        )
        values.update(invoiced=float(invoiced), netInvoiced=float(billed))
        if allowed(g.user, app_document().stored_data, "accounting"):
            values["credited"] = float(max(Decimal(0), invoiced - billed))
    return values


def links(order, customer):
    """Bound document links by separate module permissions and existing SQL team scope."""
    from .trade_api import visibility
    from .credit_api import CreditNote

    state = app_document().stored_data
    docs = []
    invoice_ids = []
    for key, field in (
        [("deliveries", "order_id"), ("customerInvoices", "order_id")]
        if customer
        else [("receipts", "po_id"), ("invoices", "po_id")]
    ):
        if not allowed(g.user, state, COLLECTIONS[key]):
            continue
        model = store.MODELS[key]
        query = select(model).where(
            getattr(model, field) == str(order["id"]), visibility(key)
        )
        if key in ("invoices", "customerInvoices"):
            invoice_ids = select(model.id).where(
                getattr(model, field) == str(order["id"]), visibility(key)
            )
        for row in db.session.scalars(
            query.order_by(model.document_date.desc(), model.id.desc()).limit(25)
        ):
            docs.append(
                dict(
                    resource=key,
                    id=row.original_id,
                    number=row.number,
                    status=row.status,
                )
            )
    if not isinstance(invoice_ids, list) and allowed(g.user, state, "accounting"):
        for note in db.session.scalars(
            select(CreditNote)
            .where(
                CreditNote.kind == ("customer" if customer else "vendor"),
                CreditNote.invoice_id.in_(invoice_ids),
            )
            .order_by(CreditNote.id.desc())
            .limit(25)
        ):
            docs.append(
                dict(
                    resource="credits",
                    id=note.id,
                    number=note.number,
                    status=note.status,
                    kind=note.kind,
                )
            )
    return docs
