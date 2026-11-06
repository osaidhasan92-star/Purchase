"""Return-credit-refund conservation against the real transaction and ledger APIs."""

from decimal import Decimal
from sqlalchemy import select, func
from backend.test_app import app, session
from backend.test_trade_api import (
    masters,
    purchase,
    receive_bill_pay,
    create,
    action,
    details,
)
from backend.app import db
from backend.erp import StockMove, StockBalance, JournalEntry, JournalLine
from backend.credit_api import CreditNote, CreditLine


def command(client, h, name, data, expected=200):
    response = client.post("/api/credits/commands/" + name, headers=h, json=data)
    assert response.status_code == expected, response.json
    return response.json.get("record")


def step(client, h, note, name, **data):
    return command(
        client,
        h,
        name,
        dict(
            id=note["id"],
            version=note["version"],
            requestKey="credit-" + name + "-" + str(step.count()),
            **data,
        ),
    )


step.n = 0


def count():
    step.n += 1
    return step.n


step.count = count


def returned(client, h, source, qty):
    with client.application.app_context():
        identity = db.session.scalar(
            select(StockMove.id).where(StockMove.source == source)
        )
    original = client.get("/api/inventory/movements/" + str(identity)).json["record"]
    response = client.post(
        "/api/inventory/commands/return",
        headers=h,
        json=dict(
            moveId=identity,
            quantity=qty,
            version=original["version"],
            reason="Customer/vendor return",
            requestKey="return-credit-" + str(count()),
        ),
    )
    assert response.status_code == 200, response.json
    return response.json["record"]


def setup_sale(app, pay=40):
    c, h = session(app)
    p, v, customer = masters(c, h)
    order = purchase(c, h, p, v)
    order, bill = receive_bill_pay(c, h, order, 20, "CREDIT-SUPPLIER-BILL")
    quote = create(
        c,
        h,
        "salesQuotations",
        customerId=customer["id"],
        items=[dict(productId=p["id"], quantity=10, rate=30, taxPercent=10)],
    )
    for s in ("submit", "approve", "send", "accept"):
        quote = action(c, h, "salesQuotations", quote, s)
    so = create(
        c, h, "salesOrders", quotationId=quote["id"], parentVersion=quote["version"]
    )
    delivery = create(
        c,
        h,
        "deliveries",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, deliveredQty=10)],
    )
    delivery = action(c, h, "deliveries", delivery, "deliver")
    so = details(c, "salesOrders", so["id"])
    inv = create(
        c,
        h,
        "customerInvoices",
        orderId=so["id"],
        parentVersion=so["version"],
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=10)],
    )
    inv = action(c, h, "customerInvoices", inv, "submit")
    inv = action(c, h, "customerInvoices", inv, "post")
    if pay:
        create(
            c,
            h,
            "customerPayments",
            invoiceId=inv["id"],
            parentVersion=inv["version"],
            amount=pay,
        )
    return c, h, p, order, bill, so, delivery, details(c, "customerInvoices", inv["id"])


def draft(c, h, kind, inv, move, qty):
    return command(
        c,
        h,
        "create",
        dict(
            kind=kind,
            invoiceId=str(inv["id"]),
            date=move["date"],
            reason="Returned goods",
            lines=[dict(lineIndex=0, quantity=qty, returnId=move["id"])],
            requestKey="draft-credit-" + str(count()),
        ),
    )


def test_customer_partial_return_credit_application_and_refund_are_conserved(app):
    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=40)
    move = returned(c, h, f'deliveries:{delivery["id"]}:0', 5)
    assert details(c, "salesOrders", so["id"])["status"] == "Partially Delivered"
    available = c.get("/api/credits/source/customer/" + str(inv["id"]))
    assert available.status_code == 200, available.json
    assert available.json["lines"][0]["returns"][0]["id"] == move["id"]
    note = draft(c, h, "customer", inv, move, 5)
    assert Decimal(note["amount"]) == Decimal("165") and note["status"] == "Draft"
    with app.app_context():
        assert (
            db.session.scalar(
                select(JournalEntry.id).where(
                    JournalEntry.source == "credit:" + str(note["id"])
                )
            )
            is None
        )
    pending = step(c, h, note, "submit")
    note = step(c, h, pending, "post")
    assert note["status"] == "Posted" and Decimal(note["remaining"]) == 0
    inv = details(c, "customerInvoices", inv["id"])
    assert (
        inv["balance"] == 125
        and inv["creditedAmount"] == 165
        and inv["paidAmount"] == 40
    )
    command(
        c,
        h,
        "refund",
        dict(
            id=note["id"],
            version=note["version"],
            amount=1,
            date=note["date"],
            requestKey="no-credit-refund",
        ),
        400,
    )
    # Pay only the net outstanding amount; gross invoice amount cannot be paid again.
    bad = c.post(
        "/api/trade/customerPayments",
        headers=h,
        json=dict(
            invoiceId=inv["id"],
            parentVersion=inv["version"],
            amount=126,
            requestKey="credit-overpayment",
        ),
    )
    assert bad.status_code == 400, bad.json
    create(
        c,
        h,
        "customerPayments",
        invoiceId=inv["id"],
        parentVersion=inv["version"],
        amount=125,
    )
    inv = details(c, "customerInvoices", inv["id"])
    assert inv["status"] == "Paid"
    move2 = returned(c, h, f'deliveries:{delivery["id"]}:0', 5)
    note2 = draft(c, h, "customer", inv, move2, 5)
    note2 = step(c, h, note2, "submit")
    note2 = step(c, h, note2, "post")
    assert Decimal(note2["remaining"]) == 165
    payload = dict(
        id=note2["id"],
        version=note2["version"],
        amount=165,
        date=note2["date"],
        account="1010",
        requestKey="refund-once-key",
    )
    refunded = command(c, h, "refund", payload)
    retry = command(c, h, "refund", payload)
    assert refunded["remaining"] == retry["remaining"] == "0.00"
    assert len(refunded["settlements"]) == 1
    command(
        c,
        h,
        "refund",
        dict(
            id=note2["id"],
            version=refunded["version"],
            amount=1,
            date=note2["date"],
            requestKey="second-refund-denied",
        ),
        400,
    )
    with app.app_context():
        balance = db.session.get(StockBalance, str(p["id"]))
        assert balance.quantity == 20 and balance.value == 200
        revenue = db.session.scalar(
            select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                JournalLine.account == "4100"
            )
        )
        assert revenue == 0
        entries = list(
            db.session.scalars(
                select(JournalEntry).where(JournalEntry.source.like("credit%"))
            )
        )
        assert len(entries) == 3
        for e in entries:
            assert sum(l.debit for l in e.lines) == sum(l.credit for l in e.lines)

    # Full returned/credited quantities may be replaced and reinvoiced once.
    so = details(c, "salesOrders", so["id"])
    assert so["status"] == "Confirmed"
    replacement = create(
        c,
        h,
        "deliveries",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, deliveredQty=10)],
    )
    action(c, h, "deliveries", replacement, "deliver")
    so = details(c, "salesOrders", so["id"])
    replacement_invoice = create(
        c,
        h,
        "customerInvoices",
        orderId=so["id"],
        parentVersion=so["version"],
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=10)],
    )
    assert (
        replacement_invoice["amount"] == 330 and replacement_invoice["taxAmount"] == 30
    )


def test_vendor_return_credit_refund_and_limits(app):
    c, h = session(app)
    p, v, _ = masters(c, h)
    po = purchase(c, h, p, v)
    po, bill = receive_bill_pay(c, h, po, 20, "VENDOR-RETURN-BILL")
    with app.app_context():
        move = db.session.scalar(
            select(StockMove).where(StockMove.kind == "Purchase Receipt")
        )
        source = move.source
    ret = returned(c, h, source, 4)
    note = draft(c, h, "vendor", bill, ret, 4)
    # Reserving the same return twice cannot consume more than its quantity.
    command(
        c,
        h,
        "create",
        dict(
            kind="vendor",
            invoiceId=str(bill["id"]),
            reason="Duplicate return",
            lines=[dict(lineIndex=0, quantity=1, returnId=ret["id"])],
            requestKey="duplicate-return-credit",
        ),
        400,
    )
    note = step(c, h, note, "submit")
    note = step(c, h, note, "post")
    assert Decimal(note["remaining"]) == 40
    note = step(c, h, note, "refund", amount=40, date=note["date"], account="1000")
    assert Decimal(note["remaining"]) == 0
    with app.app_context():
        grni = db.session.scalar(
            select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                JournalLine.account == "2105"
            )
        )
        assert grni == 0
        assert db.session.get(StockBalance, str(p["id"])).quantity == 16

    po = details(c, "orders", po["id"])
    assert po["status"] == "Partially Received"
    create(
        c,
        h,
        "receipts",
        poId=po["id"],
        parentVersion=po["version"],
        items=[dict(lineIndex=0, receivedQty=4, acceptedQty=4, rejectedQty=0)],
    )
    po = details(c, "orders", po["id"])
    replacement = create(
        c,
        h,
        "invoices",
        poId=po["id"],
        parentVersion=po["version"],
        invoiceNo="REPLACEMENT-VENDOR-BILL",
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=4)],
    )
    assert replacement["amount"] == 40 and replacement["matchStatus"] == "Matched"
    replacement = action(c, h, "invoices", replacement, "submit")
    action(c, h, "invoices", replacement, "post")
    with app.app_context():
        assert (
            db.session.scalar(
                select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                    JournalLine.account == "2105"
                )
            )
            == 0
        )


def test_credit_permissions_cancellation_and_stale_versions(app):
    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=330)
    ret = returned(c, h, f'deliveries:{delivery["id"]}:0', 1)
    note = draft(c, h, "customer", inv, ret, 1)
    manager, mh = session(app, "manager")
    assert manager.get("/api/credits?kind=customer").status_code == 403
    command(
        manager,
        mh,
        "post",
        dict(id=note["id"], version=note["version"], requestKey="sales-credit-denied"),
        403,
    )
    submitted = step(c, h, note, "submit")
    command(
        c,
        h,
        "post",
        dict(id=note["id"], version=note["version"], requestKey="stale-credit-post"),
        409,
    )
    cancelled = step(c, h, submitted, "cancel")
    assert cancelled["status"] == "Cancelled"
    replacement = draft(c, h, "customer", inv, ret, 1)
    assert replacement["status"] == "Draft"


def test_available_credit_applies_only_to_same_partner_and_cannot_refund_twice(app):
    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=330)
    ret = returned(c, h, f'deliveries:{delivery["id"]}:0', 1)
    note = draft(c, h, "customer", inv, ret, 1)
    note = step(c, h, note, "submit")
    note = step(c, h, note, "post")

    def target(customer):
        quote = create(
            c,
            h,
            "salesQuotations",
            customerId=customer,
            items=[dict(productId=p["id"], quantity=1, rate=30, taxPercent=10)],
        )
        for s in ("submit", "approve", "send", "accept"):
            quote = action(c, h, "salesQuotations", quote, s)
        order = create(
            c, h, "salesOrders", quotationId=quote["id"], parentVersion=quote["version"]
        )
        invoice = create(
            c,
            h,
            "customerInvoices",
            orderId=order["id"],
            parentVersion=order["version"],
            dueDate="2027-12-31",
            items=[dict(lineIndex=0, quantity=1)],
        )
        invoice = action(c, h, "customerInvoices", invoice, "submit")
        return action(c, h, "customerInvoices", invoice, "post")

    other = c.post(
        "/api/customers",
        headers=h,
        json=dict(name="Another credit customer", requestKey="other-credit-customer"),
    ).json["customer"]
    wrong = target(other["id"])
    correct = target(inv["customerId"])
    command(
        c,
        h,
        "apply",
        dict(
            id=note["id"],
            version=note["version"],
            invoiceId=str(wrong["id"]),
            amount=33,
            date=note["date"],
            requestKey="wrong-partner-credit",
        ),
        400,
    )
    with app.app_context():
        credit_line = db.session.scalar(
            select(JournalLine.id).where(
                JournalLine.entry_id == note["journalId"], JournalLine.account == "1100"
            )
        )
        target_entry = db.session.scalar(
            select(JournalEntry.id).where(
                JournalEntry.source == "customerInvoices:" + str(correct["id"])
            )
        )
        target_line = db.session.scalar(
            select(JournalLine.id).where(
                JournalLine.entry_id == target_entry, JournalLine.account == "1100"
            )
        )
    bypass = c.post(
        "/api/erp/reconcile",
        headers=h,
        json=dict(debitLine=target_line, creditLine=credit_line, amount=33),
    )
    assert bypass.status_code == 400, bypass.json
    applied = step(
        c, h, note, "apply", invoiceId=str(correct["id"]), amount=33, date=note["date"]
    )
    assert Decimal(applied["remaining"]) == 0
    cleared = details(c, "customerInvoices", correct["id"])
    assert (
        cleared["status"] == "Paid"
        and cleared["paidAmount"] == 0
        and cleared["creditedAmount"] == 33
        and cleared["balance"] == 0
    )
    command(
        c,
        h,
        "refund",
        dict(
            id=applied["id"],
            version=applied["version"],
            amount=1,
            date=note["date"],
            requestKey="applied-credit-refund",
        ),
        400,
    )


def test_service_credit_needs_no_stock_and_locked_period_cannot_post(app):
    c, h = session(app)
    customer = c.post(
        "/api/customers",
        headers=h,
        json=dict(name="Service customer", requestKey="service-credit-customer"),
    ).json["customer"]
    product = c.post(
        "/api/products",
        headers=h,
        json=dict(
            name="Consultancy",
            sku="CREDIT-SERVICE",
            rate=10,
            unit="Service",
            productType="service",
            requestKey="service-credit-product",
        ),
    ).json["record"]
    quote = create(
        c,
        h,
        "salesQuotations",
        customerId=customer["id"],
        items=[dict(productId=product["id"], quantity=3, rate=10, taxPercent=10)],
    )
    for s in ("submit", "approve", "send", "accept"):
        quote = action(c, h, "salesQuotations", quote, s)
    order = create(
        c, h, "salesOrders", quotationId=quote["id"], parentVersion=quote["version"]
    )
    inv = create(
        c,
        h,
        "customerInvoices",
        orderId=order["id"],
        parentVersion=order["version"],
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=3)],
    )
    inv = action(c, h, "customerInvoices", inv, "submit")
    inv = action(c, h, "customerInvoices", inv, "post")
    note = command(
        c,
        h,
        "create",
        dict(
            kind="customer",
            invoiceId=str(inv["id"]),
            reason="Cancelled service",
            lines=[dict(lineIndex=0, quantity=1)],
            requestKey="service-credit-draft",
        ),
    )
    note = step(c, h, note, "submit")
    posted = step(c, h, note, "post")
    assert (
        Decimal(posted["amount"]) == 11
        and Decimal(posted["tax"]) == 1
        and Decimal(posted["remaining"]) == 0
    )
    assert details(c, "customerInvoices", inv["id"])["balance"] == 22
    note = command(
        c,
        h,
        "create",
        dict(
            kind="customer",
            invoiceId=str(inv["id"]),
            reason="Second service credit",
            lines=[dict(lineIndex=0, quantity=1)],
            requestKey="service-credit-locked",
        ),
    )
    note = step(c, h, note, "submit")
    from backend.erp import ERPControl

    with app.app_context():
        db.session.get(ERPControl, 1).lock_date = note["date"]
        db.session.commit()
    command(
        c,
        h,
        "post",
        dict(id=note["id"], version=note["version"], requestKey="locked-credit-post"),
        400,
    )
    assert (
        c.get("/api/credits/" + str(note["id"])).json["record"]["status"]
        == "Pending Review"
    )
    with app.app_context():
        assert (
            db.session.scalar(
                select(JournalEntry.id).where(
                    JournalEntry.source == "credit:" + str(note["id"])
                )
            )
            is None
        )


def test_vendor_return_average_cost_variance_clears_return_accrual(app):
    c, h = session(app)
    product, vendor, _ = masters(c, h)
    po = purchase(c, h, product, vendor)
    po, bill = receive_bill_pay(c, h, po, 20, "AVERAGE-RETURN-BILL")
    current = c.get("/api/inventory/products/" + str(product["id"])).json["record"]
    adjusted = c.post(
        "/api/inventory/commands/adjust",
        headers=h,
        json=dict(
            productId=product["id"],
            version=current["version"],
            quantity=20,
            unitCost=20,
            reason="Higher-cost incoming stock",
            requestKey="credit-variance-stock",
        ),
    )
    assert adjusted.status_code == 200, adjusted.json
    with app.app_context():
        source = db.session.scalar(
            select(StockMove.source).where(StockMove.kind == "Purchase Receipt")
        )
    ret = returned(c, h, source, 4)
    assert Decimal(ret["value"]) == -60
    note = draft(c, h, "vendor", bill, ret, 4)
    note = step(c, h, note, "submit")
    note = step(c, h, note, "post")
    with app.app_context():
        assert (
            db.session.scalar(
                select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                    JournalLine.account == "2105"
                )
            )
            == 0
        )
        credit_entry = db.session.get(JournalEntry, note["journalId"])
        variance = next(l for l in credit_entry.lines if l.account == "5105")
        assert variance.debit == 20 and variance.credit == 0
        assert (
            sum(l.debit for l in credit_entry.lines)
            == sum(l.credit for l in credit_entry.lines)
            == 60
        )


def test_upgrade_adds_credit_tables_without_reposting_existing_documents(app):
    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=330)
    from backend.credit_api import CreditCommand, CreditSettlement

    with app.app_context():
        before = db.session.scalar(select(func.count()).select_from(JournalEntry))
        db.session.remove()
        for model in (CreditCommand, CreditSettlement, CreditLine, CreditNote):
            model.__table__.drop(db.engine)
    for _ in range(2):
        migrated = app.test_cli_runner().invoke(args=["migrate-storage"])
        assert migrated.exit_code == 0, migrated.output
        with app.app_context():
            assert (
                db.session.scalar(select(func.count()).select_from(JournalEntry))
                == before
            )
            assert db.session.scalar(select(func.count()).select_from(CreditNote)) == 0
    assert details(c, "customerInvoices", inv["id"])["status"] == "Paid"
