"""Closed remainders preserve financial obligations and cannot reopen on returns."""

from decimal import Decimal
from copy import deepcopy
from sqlalchemy import select, func
from backend.test_app import app, session
from backend.test_trade_api import (
    masters,
    purchase,
    receive_bill_pay,
    create,
    action,
    details,
    post,
)
from backend.test_credit_api import setup_sale, returned, draft, step
from backend.test_warehouse_api import sale, product, transfer
from backend.app import db, Document
from backend.erp import JournalEntry, StockMove


def context(c, key, row):
    return c.get("/api/trade/" + key + "/" + str(row["id"])).json["context"]


def close(
    c,
    h,
    key,
    row,
    reason="Customer/supplier declined replacement",
    expected=200,
    request_key="close-remainder-test",
):
    return post(
        c,
        h,
        key + "/" + str(row["id"]) + "/actions/close",
        dict(version=row["version"], reason=reason, requestKey=request_key),
        expected,
    )


def test_sales_return_credit_refund_close_and_later_return_stays_closed(app):
    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=330)
    move = returned(c, h, f'deliveries:{delivery["id"]}:0', 3)
    so = details(c, "salesOrders", so["id"])
    close(c, h, "salesOrders", so, expected=400)
    note = step(
        c, h, step(c, h, draft(c, h, "customer", inv, move, 3), "submit"), "post"
    )
    so = details(c, "salesOrders", so["id"])
    payload = dict(
        version=so["version"],
        reason="No replacement requested",
        requestKey="sales-close-repeat",
    )
    with app.app_context():
        journals = db.session.scalar(select(func.count()).select_from(JournalEntry))
    closed = post(c, h, "salesOrders/" + str(so["id"]) + "/actions/close", payload)
    assert (
        closed["status"] == "Closed"
        and closed["closeReason"] == "No replacement requested"
    )
    assert (
        post(c, h, "salesOrders/" + str(so["id"]) + "/actions/close", payload)["id"]
        == closed["id"]
    )
    post(
        c,
        h,
        "salesOrders/" + str(so["id"]) + "/actions/close",
        {**payload, "reason": "Changed reason"},
        409,
    )
    with app.app_context():
        assert (
            db.session.scalar(select(func.count()).select_from(JournalEntry))
            == journals
        )
    line = context(c, "salesOrders", closed)["lines"][0]
    assert (
        line["fulfilled"],
        line["returned"],
        line["credited"],
        line["remaining"],
        line["closedRemaining"],
    ) == (10, 3, 3, 0, 3)
    assert Decimal(product(c, p)["reserved"]) == 0
    assert c.get("/api/warehouse/backorders").json["items"] == []
    # Finance may refund the posted credit after operational closure.
    step(
        c,
        h,
        note,
        "refund",
        amount=99,
        account="1010",
        date=move["date"],
    )
    create_payload = dict(
        orderId=closed["id"],
        parentVersion=closed["version"],
        items=[dict(lineIndex=0, deliveredQty=1)],
        requestKey="closed-delivery-denied",
    )
    post(c, h, "deliveries", create_payload, 400)
    returned(c, h, f'deliveries:{delivery["id"]}:0', 1)
    closed = details(c, "salesOrders", closed["id"])
    assert (
        closed["status"] == "Closed"
        and context(c, "salesOrders", closed)["lines"][0]["remaining"] == 0
    )
    assert Decimal(product(c, p)["reserved"]) == 0
    assert c.get("/api/warehouse/backorders").json["items"] == []
    printed = c.get("/api/trade/salesOrders/" + str(closed["id"]) + "/print")
    assert printed.status_code == 200 and b"No replacement requested" in printed.data


def test_purchase_return_vendor_credit_refund_and_closed_bill_limits(app):
    c, h = session(app)
    p, v, _ = masters(c, h)
    po = purchase(c, h, p, v)
    po, bill = receive_bill_pay(c, h, po, 12, "CLOSE-PURCHASE-BILL")
    receipt = c.get("/api/trade/receipts").json["items"][0]
    move = returned(c, h, f'receipts:{receipt["id"]}:0', 2)
    po = details(c, "orders", po["id"])
    close(c, h, "orders", po, expected=400)
    note = step(
        c, h, step(c, h, draft(c, h, "vendor", bill, move, 2), "submit"), "post"
    )
    po = close(c, h, "orders", details(c, "orders", po["id"]))
    line = context(c, "orders", po)["lines"][0]
    assert (
        line["fulfilled"],
        line["returned"],
        line["credited"],
        line["remaining"],
        line["closedRemaining"],
    ) == (12, 2, 2, 0, 10)
    step(
        c,
        h,
        note,
        "refund",
        amount=20,
        account="1010",
        date=move["date"],
    )
    assert details(c, "orders", po["id"])["status"] == "Closed"
    post(
        c,
        h,
        "receipts",
        dict(
            poId=po["id"],
            parentVersion=po["version"],
            items=[dict(lineIndex=0, receivedQty=1, acceptedQty=1, rejectedQty=0)],
            requestKey="closed-receipt-denied",
        ),
        400,
    )
    current = details(c, "orders", po["id"])
    post(
        c,
        h,
        "invoices",
        dict(
            poId=po["id"],
            parentVersion=current["version"],
            invoiceNo="CLOSED-EXCESS",
            dueDate="2027-12-31",
            items=[dict(lineIndex=0, quantity=1)],
            requestKey="closed-bill-denied",
        ),
        400,
    )


def test_partial_close_allows_actual_invoicing_and_keeps_payments(app):
    c, h = session(app)
    p, v, customer = masters(c, h)
    po = purchase(c, h, p, v)
    receive_bill_pay(c, h, po, 20, "CLOSE-PARTIAL-STOCK")
    so = sale(c, h, p, customer, 10)
    delivery = create(
        c,
        h,
        "deliveries",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, deliveredQty=4)],
    )
    action(c, h, "deliveries", delivery, "deliver")
    so = details(c, "salesOrders", so["id"])
    close(c, h, "salesOrders", so, reason="", expected=400)
    pending = create(
        c,
        h,
        "deliveries",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, deliveredQty=2)],
    )
    close(c, h, "salesOrders", details(c, "salesOrders", so["id"]), expected=400)
    action(c, h, "deliveries", pending, "cancel")
    so = close(c, h, "salesOrders", details(c, "salesOrders", so["id"]))
    assert context(c, "salesOrders", so)["lines"][0]["billableRemaining"] == 4
    invoice = create(
        c,
        h,
        "customerInvoices",
        orderId=so["id"],
        parentVersion=so["version"],
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=4)],
    )
    invoice = action(
        c,
        h,
        "customerInvoices",
        action(c, h, "customerInvoices", invoice, "submit"),
        "post",
    )
    create(
        c,
        h,
        "customerPayments",
        invoiceId=invoice["id"],
        parentVersion=invoice["version"],
        amount=80,
    )
    current = details(c, "salesOrders", so["id"])
    assert (
        current["status"] == "Closed"
        and current["paymentStatus"] == "Paid"
        and current["invoiceStatus"] == "Invoiced"
    )
    assert Decimal(product(c, p)["reserved"]) == 0


def test_close_permissions_restricted_quantities_and_new_orders(app):
    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=0)
    move = returned(c, h, f'deliveries:{delivery["id"]}:0', 1)
    viewer, vh = session(app, "viewer")
    with app.app_context():
        doc = db.session.get(Document, "app")
        data = deepcopy(doc.data)
        data["roles"]["Viewer"]["permissions"]["sales_orders"] = dict(
            view=True, create=False, edit=False, approve=False, export=False
        )
        for module in ("sales_invoices", "sales_payments", "accounting"):
            data["roles"]["Viewer"]["permissions"][module] = dict(
                view=False, create=False, edit=False, approve=False, export=False
            )
        # Order ownership grants operational scope without financial module access.
        from backend.trade_store import MODELS

        row = db.session.get(MODELS["salesOrders"], str(so["id"]))
        row.owner_id = "viewer"
        doc.data = data
        db.session.commit()
    # Admin read verifies absence of accidental zero fallback independently of team scope.
    response = viewer.get("/api/trade/salesOrders/" + str(so["id"]))
    assert response.status_code == 200, response.json
    ctx = response.json["context"]
    assert ctx["financialQuantitiesAvailable"] is False
    assert "invoiced" not in ctx["lines"][0] and "credited" not in ctx["lines"][0]
    assert all(
        doc["resource"] not in ("customerInvoices", "credits")
        for doc in ctx["relatedDocuments"]
    )
    denied = viewer.post(
        "/api/trade/salesOrders/" + str(so["id"]) + "/actions/close",
        headers=vh,
        json=dict(
            version=details(c, "salesOrders", so["id"])["version"],
            reason="Not approved",
            requestKey="viewer-close-denied",
        ),
    )
    assert denied.status_code == 403
    with app.app_context():
        doc = db.session.get(Document, "app")
        data = deepcopy(doc.data)
        data["roles"]["Viewer"]["permissions"]["sales_invoices"]["view"] = True
        doc.data = data
        db.session.commit()
    readable = viewer.get("/api/trade/salesOrders/" + str(so["id"])).json["context"]
    assert readable["financialQuantitiesAvailable"] is True
    assert readable["creditQuantitiesAvailable"] is False
    assert (
        readable["lines"][0]["invoiced"] == 10
        and "credited" not in readable["lines"][0]
    )
    new = sale(c, h, p, {"id": so["customerId"]}, 1)
    close(
        c, h, "salesOrders", new, expected=400, request_key="unfulfilled-close-denied"
    )


def test_rejected_receipt_can_close_without_stock_or_financial_posting(app):
    c, h = session(app)
    p, v, _ = masters(c, h)
    po = purchase(c, h, p, v)
    create(
        c,
        h,
        "receipts",
        poId=po["id"],
        parentVersion=po["version"],
        items=[
            dict(
                lineIndex=0,
                receivedQty=5,
                acceptedQty=0,
                rejectedQty=5,
                inspection="Rejected",
                remark="Damaged on arrival",
            )
        ],
    )
    po = close(c, h, "orders", details(c, "orders", po["id"]))
    line = context(c, "orders", po)["lines"][0]
    assert line["receivedForInspection"] == 5 and line["rejected"] == 5
    assert line["closedRemaining"] == 20 and line["remaining"] == 0
    assert Decimal(product(c, p)["quantity"]) == 0


def test_close_uses_current_version_and_blocks_excess_invoice_drafts(app):
    c, h = session(app)
    p, v, customer = masters(c, h)
    po = purchase(c, h, p, v)
    receive_bill_pay(c, h, po, 20, "CLOSE-DRAFTS-STOCK")
    so = sale(c, h, p, customer, 10)
    old = so
    delivery = create(
        c,
        h,
        "deliveries",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, deliveredQty=4)],
    )
    action(c, h, "deliveries", delivery, "deliver")
    close(c, h, "salesOrders", old, expected=409, request_key="stale-close-denied")
    so = details(c, "salesOrders", so["id"])
    invoice = create(
        c,
        h,
        "customerInvoices",
        orderId=so["id"],
        parentVersion=so["version"],
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=10)],
    )
    close(
        c,
        h,
        "salesOrders",
        details(c, "salesOrders", so["id"]),
        expected=400,
        request_key="excess-draft-close-denied",
    )
    action(c, h, "customerInvoices", invoice, "cancel")
    assert (
        close(c, h, "salesOrders", details(c, "salesOrders", so["id"]))["status"]
        == "Closed"
    )


def test_close_and_delivery_creation_serialize_one_order(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    c, h = session(app)
    p, v, customer = masters(c, h)
    po = purchase(c, h, p, v)
    receive_bill_pay(c, h, po, 20, "CLOSE-RACE-STOCK")
    so = sale(c, h, p, customer, 10)
    delivery = create(
        c,
        h,
        "deliveries",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, deliveredQty=4)],
    )
    action(c, h, "deliveries", delivery, "deliver")
    so = details(c, "salesOrders", so["id"])
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def command(index):
        client, headers = clients[index]
        barrier.wait(timeout=10)
        endpoint = (
            "/api/trade/salesOrders/" + str(so["id"]) + "/actions/close"
            if index == 0
            else "/api/trade/deliveries"
        )
        payload = (
            dict(
                version=so["version"],
                reason="Remainder declined",
                requestKey="concurrent-close",
            )
            if index == 0
            else dict(
                orderId=so["id"],
                parentVersion=so["version"],
                items=[dict(lineIndex=0, deliveredQty=2)],
                requestKey="concurrent-delivery",
            )
        )
        return client.post(endpoint, headers=headers, json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(command, range(2)))
    assert codes.count(200) == 1 and all(
        code in (200, 400, 409) for code in codes
    ), codes
    current = details(c, "salesOrders", so["id"])
    pending = [
        row
        for row in c.get("/api/trade/deliveries?orderId=" + str(so["id"])).json["items"]
        if row["status"] == "Pending"
    ]
    assert (current["status"] == "Closed" and not pending) or (
        current["status"] != "Closed" and len(pending) == 1
    )


def test_fully_returned_and_credited_order_can_close_without_false_unpaid_status(app):
    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=330)
    move = returned(c, h, f'deliveries:{delivery["id"]}:0', 10)
    note = step(
        c, h, step(c, h, draft(c, h, "customer", inv, move, 10), "submit"), "post"
    )
    closed = close(c, h, "salesOrders", details(c, "salesOrders", so["id"]))
    assert closed["status"] == "Closed" and closed["invoiceStatus"] == "Fully Credited"
    assert closed["paymentStatus"] == "No Balance Due"
    assert context(c, "salesOrders", closed)["lines"][0]["closedRemaining"] == 10
    assert (
        Decimal(note["remaining"]) == 330
    )  # Still a refund obligation, independent of customer receivables.
    step(c, h, note, "refund", amount=330, account="1010", date=move["date"])
    assert details(c, "salesOrders", closed["id"])["status"] == "Closed"
