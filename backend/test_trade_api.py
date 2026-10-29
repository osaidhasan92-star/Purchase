"""Native command simulations; independent totals and privacy checks."""

import pytest
from copy import deepcopy
from decimal import Decimal
from sqlalchemy import select
from backend.test_app import app, session, patch
from backend.app import db, Document
from backend import trade_store as store
from backend.erp import JournalEntry, StockMove


@pytest.fixture(autouse=True)
def native_only_transport(app):
    app.config["ENABLE_LEGACY_TRADE_WRITES"] = False


def post(client, h, key, payload, expected=200):
    response = client.post("/api/trade/" + key, headers=h, json=payload)
    assert response.status_code == expected, response.json
    return response.json.get("record")


def details(client, key, identity):
    response = client.get(f"/api/trade/{key}/{identity}")
    assert response.status_code == 200, response.json
    return response.json["record"]


def create(client, h, key, **data):
    return post(
        client,
        h,
        key,
        {"requestKey": "native-" + key + "-" + str(create.counter()), **data},
    )


create._count = 0


def counter():
    create._count += 1
    return create._count


create.counter = counter


def action(client, h, key, row, command):
    return post(
        client,
        h,
        f'{key}/{row["id"]}/actions/{command}',
        {
            "version": row["version"],
            "requestKey": key + "-" + command + "-" + str(counter()),
        },
    )


def masters(client, h):
    product = client.post(
        "/api/products",
        headers=h,
        json={
            "name": "Native stock",
            "sku": "NATIVE-STK",
            "rate": 10,
            "requestKey": "native-product-0001",
        },
    ).json["record"]
    vendor = client.post(
        "/api/vendors",
        headers=h,
        json={"name": "Native vendor", "requestKey": "native-vendor-0001"},
    ).json["record"]
    customer = client.post(
        "/api/customers",
        headers=h,
        json={"name": "Native customer", "requestKey": "native-customer-0001"},
    ).json["customer"]
    return product, vendor, customer


def purchase(client, h, product, vendor):
    req = create(
        client,
        h,
        "requests",
        department="Operations",
        items=[dict(productId=product["id"], quantity=20, rate=10)],
    )
    req = action(client, h, "requests", req, "submit")
    req = action(client, h, "requests", req, "approve")
    rfq = create(
        client,
        h,
        "rfqs",
        requestId=req["id"],
        parentVersion=req["version"],
        vendorIds=[vendor["id"]],
        dueDate="2027-12-31",
    )
    rfq = action(client, h, "rfqs", rfq, "send")
    quote = create(
        client,
        h,
        "quotations",
        rfqId=rfq["id"],
        parentVersion=rfq["version"],
        vendorId=vendor["id"],
        validUntil="2027-12-31",
        items=[dict(productId=product["id"], quantity=20, rate=10)],
    )
    quote = action(client, h, "quotations", quote, "award")
    order = create(
        client,
        h,
        "orders",
        quotationId=quote["id"],
        parentVersion=quote["version"],
        deliveryDate="2027-12-31",
    )
    for step in ("submit", "approve", "send"):
        order = action(client, h, "orders", order, step)
    return order


def receive_bill_pay(client, h, order, quantity, invoice_number, pay_amount=None):
    create(
        client,
        h,
        "receipts",
        poId=order["id"],
        parentVersion=order["version"],
        items=[
            dict(lineIndex=0, receivedQty=quantity, acceptedQty=quantity, rejectedQty=0)
        ],
    )
    order = details(client, "orders", order["id"])
    bill = create(
        client,
        h,
        "invoices",
        poId=order["id"],
        parentVersion=order["version"],
        invoiceNo=invoice_number,
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=quantity)],
    )
    assert bill["status"] == "Matched"
    bill = action(client, h, "invoices", bill, "approve")
    create(
        client,
        h,
        "payments",
        invoiceId=bill["id"],
        parentVersion=bill["version"],
        amount=pay_amount or bill["amount"],
        method="Bank Transfer",
    )
    return details(client, "orders", order["id"]), details(
        client, "invoices", bill["id"]
    )


def test_native_purchase_partial_receipts_bills_payments_are_atomic_and_relational(app):
    client, h = session(app)
    product, vendor, customer = masters(client, h)
    order = purchase(client, h, product, vendor)
    order, bill = receive_bill_pay(client, h, order, 10, "NATIVE-BILL-1", 40)
    assert (
        order["status"] == "Partially Received"
        and bill["balance"] == 60
        and bill["status"] == "Partially Paid"
    )
    create(
        client,
        h,
        "payments",
        invoiceId=bill["id"],
        parentVersion=bill["version"],
        amount=60,
        method="Bank Transfer",
    )
    order = details(client, "orders", order["id"])
    assert order["status"] == "Partially Received"
    order, bill = receive_bill_pay(client, h, order, 10, "NATIVE-BILL-2")
    assert order["status"] == "Completed" and bill["status"] == "Paid"
    stock = client.get("/api/erp/inventory").json
    assert (
        Decimal(
            next(p for p in stock["products"] if p["id"] == str(product["id"]))[
                "quantity"
            ]
        )
        == 20
    )
    with app.app_context():
        doc = db.session.get(Document, "app")
        assert doc.stored_data[store.MARKER] and all(
            k not in doc.stored_data for k in store.SPECS
        )
        header = db.session.get(store.MODELS["orders"], str(order["id"]))
        assert header.vendor_id == str(vendor["id"]) and len(header.lines) == 1
        assert header.lines[0].product_id == str(product["id"])
        assert (
            len(
                db.session.scalars(
                    select(JournalEntry).where(JournalEntry.source.like("payments:%"))
                ).all()
            )
            == 3
        )


def test_native_sales_approval_partial_deliveries_invoices_and_collections(app):
    client, h = session(app)
    product, vendor, customer = masters(client, h)
    order = purchase(client, h, product, vendor)
    order, _ = receive_bill_pay(client, h, order, 20, "STOCK-BILL")
    quote = create(
        client,
        h,
        "salesQuotations",
        customerId=customer["id"],
        items=[
            dict(
                productId=product["id"],
                quantity=4,
                rate=30,
                taxPercent=5,
                discountPercent=10,
            )
        ],
    )
    assert quote["total"] == 113.4
    for step in ("submit", "approve", "send", "accept"):
        quote = action(client, h, "salesQuotations", quote, step)
    so = create(
        client,
        h,
        "salesOrders",
        quotationId=quote["id"],
        parentVersion=quote["version"],
    )
    delivery = create(
        client,
        h,
        "deliveries",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, deliveredQty=2)],
    )
    assert delivery["status"] == "Pending"
    delivery = action(client, h, "deliveries", delivery, "deliver")
    so = details(client, "salesOrders", so["id"])
    assert so["status"] == "Partially Delivered"
    invoice = create(
        client,
        h,
        "customerInvoices",
        orderId=so["id"],
        parentVersion=so["version"],
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=2)],
    )
    assert invoice["amount"] == 56.7 and invoice["taxAmount"] == 2.7
    payment = create(
        client,
        h,
        "customerPayments",
        invoiceId=invoice["id"],
        parentVersion=invoice["version"],
        amount=20,
        method="Cash",
    )
    invoice = details(client, "customerInvoices", invoice["id"])
    assert invoice["balance"] == 36.7
    create(
        client,
        h,
        "customerPayments",
        invoiceId=invoice["id"],
        parentVersion=invoice["version"],
        amount=36.7,
        method="Cash",
    )
    so = details(client, "salesOrders", so["id"])
    assert so["status"] == "Partially Delivered"
    delivery = create(
        client,
        h,
        "deliveries",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, deliveredQty=2)],
    )
    action(client, h, "deliveries", delivery, "deliver")
    so = details(client, "salesOrders", so["id"])
    invoice = create(
        client,
        h,
        "customerInvoices",
        orderId=so["id"],
        parentVersion=so["version"],
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=2)],
    )
    create(
        client,
        h,
        "customerPayments",
        invoiceId=invoice["id"],
        parentVersion=invoice["version"],
        amount=56.7,
        method="Cash",
    )
    assert details(client, "salesOrders", so["id"])["status"] == "Completed"
    report = client.get("/api/erp/reports").json
    assert (
        Decimal(report["receivables"]) == 0
        and Decimal(report["payables"]) == 0
        and Decimal(report["balanceCheck"]) == 0
    )
    challan = client.get(f'/api/trade/deliveries/{delivery["id"]}/print')
    assert (
        challan.status_code == 200
        and b"Delivery Challan" in challan.data
        and b"Complete source quotation" in challan.data
    )


def test_trade_versions_idempotency_validation_and_privacy(app):
    admin, h = session(app)
    product, vendor, customer = masters(admin, h)
    seller, sh = session(app, "seller")
    quote = create(
        seller,
        sh,
        "salesQuotations",
        customerId=customer["id"],
        items=[dict(productId=product["id"], quantity=1, rate=10)],
    )
    viewer, vh = session(app, "viewer")
    assert viewer.get("/api/trade/salesQuotations").json["total"] == 0
    assert (
        viewer.get("/api/trade/salesQuotations/" + str(quote["id"])).status_code == 404
    )
    assert (
        viewer.get(
            "/api/trade/salesQuotations/" + str(quote["id"]) + "/print"
        ).status_code
        == 404
    )
    pending = action(seller, sh, "salesQuotations", quote, "submit")
    post(
        seller,
        sh,
        f'salesQuotations/{quote["id"]}/actions/approve',
        {"version": pending["version"], "requestKey": "seller-approval-forgery"},
        403,
    )
    manager, mh = session(app, "manager")
    approved = action(manager, mh, "salesQuotations", pending, "approve")
    post(
        seller,
        sh,
        f'salesQuotations/{quote["id"]}/actions/submit',
        {"version": quote["version"], "requestKey": "stale-quote-submit"},
        409,
    )
    payload = {
        "customerId": customer["id"],
        "requestKey": "idempotent-trade-key",
        "items": [dict(productId=product["id"], quantity=1, rate=10)],
    }
    a = post(seller, sh, "salesQuotations", payload)
    b = post(seller, sh, "salesQuotations", payload)
    assert a["id"] == b["id"]
    post(seller, sh, "salesQuotations", {**payload, "customerId": "missing"}, 409)
    post(
        admin,
        h,
        "orders",
        {
            "vendorId": vendor["id"],
            "deliveryDate": "2027-12-31",
            "requestKey": "forged-order-total",
            "items": [dict(productId=product["id"], quantity=1, rate=10)],
            "total": 1,
        },
        400,
    )
    post(
        admin,
        h,
        "salesOrders",
        {
            "quotationId": approved["id"],
            "parentVersion": approved["version"],
            "requestKey": "unaccepted-order-key",
        },
        400,
    )
    assert admin.get("/api/trade/salesQuotations?pageSize=101").status_code == 400
    assert (
        viewer.post("/api/trade/salesQuotations", headers=vh, json=payload).status_code
        == 403
    )


def test_default_aggregate_transaction_writes_are_retired(app):
    client, h = session(app)
    response = patch(client, h, {"orders": []})
    assert response.status_code == 410
    assert "document/action APIs" in response.json["error"]
    # Master/HR compatibility is independent of retired trade writes.
    assert (
        patch(client, h, {"customers": [dict(id=81, name="Still shared")]}).status_code
        == 200
    )


def test_native_conservation_stale_sources_and_financial_idempotency(app):
    client, h = session(app)
    product, vendor, customer = masters(client, h)
    order = purchase(client, h, product, vendor)
    payload = dict(
        poId=order["id"],
        parentVersion=order["version"],
        requestKey="same-receipt-native",
        items=[dict(lineIndex=0, receivedQty=8, acceptedQty=5, rejectedQty=3)],
    )
    receipt = post(client, h, "receipts", payload)
    assert post(client, h, "receipts", payload)["id"] == receipt["id"]
    # The header version changes once fulfilment starts, preventing stale source submissions.
    post(client, h, "receipts", {**payload, "requestKey": "different-receipt-key"}, 409)
    order = details(client, "orders", order["id"])
    post(
        client,
        h,
        "receipts",
        dict(
            poId=order["id"],
            parentVersion=order["version"],
            requestKey="over-receipt-key",
            items=[dict(lineIndex=0, receivedQty=16, acceptedQty=16, rejectedQty=0)],
        ),
        400,
    )
    bill = create(
        client,
        h,
        "invoices",
        poId=order["id"],
        parentVersion=order["version"],
        invoiceNo="NATIVE-EXCEPTION",
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=6)],
    )
    assert bill["status"] == "Exception"
    post(
        client,
        h,
        f'invoices/{bill["id"]}/actions/approve',
        {"version": bill["version"], "requestKey": "approve-exception-bill"},
        409,
    )
    # A smaller valid bill may be paid only within its true remaining balance.
    bill = create(
        client,
        h,
        "invoices",
        poId=order["id"],
        parentVersion=order["version"],
        invoiceNo="NATIVE-VALID",
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=5)],
    )
    bill = action(client, h, "invoices", bill, "approve")
    payment = dict(
        invoiceId=bill["id"],
        parentVersion=bill["version"],
        requestKey="same-payment-native",
        amount=20,
        method="Cash",
    )
    paid = post(client, h, "payments", payment)
    assert post(client, h, "payments", payment)["id"] == paid["id"]
    bill = details(client, "invoices", bill["id"])
    post(
        client,
        h,
        "payments",
        {
            **payment,
            "requestKey": "too-large-native-payment",
            "parentVersion": bill["version"],
            "amount": 31,
        },
        400,
    )
    assert details(client, "invoices", bill["id"])["balance"] == 30
    with app.app_context():
        assert (
            len(
                db.session.scalars(
                    select(StockMove).where(StockMove.source.like("receipts:%"))
                ).all()
            )
            == 1
        )
        assert (
            len(
                db.session.scalars(
                    select(JournalEntry).where(JournalEntry.source.like("payments:%"))
                ).all()
            )
            == 1
        )


def test_native_mixed_stock_and_service_bills_use_actual_partial_line_allocation(app):
    client, h = session(app)
    product, vendor, customer = masters(client, h)
    service = client.post(
        "/api/products",
        headers=h,
        json={
            "name": "Installation",
            "productType": "service",
            "unit": "Service",
            "requestKey": "native-service-product",
        },
    ).json["record"]
    order = create(
        client,
        h,
        "orders",
        vendorId=vendor["id"],
        deliveryDate="2027-12-31",
        items=[
            dict(productId=product["id"], quantity=10, rate=10),
            dict(productId=service["id"], quantity=1, rate=50),
        ],
    )
    for step in ("submit", "approve", "send"):
        order = action(client, h, "orders", order, step)
    create(
        client,
        h,
        "receipts",
        poId=order["id"],
        parentVersion=order["version"],
        items=[
            dict(lineIndex=0, receivedQty=5, acceptedQty=5, rejectedQty=0),
            dict(lineIndex=1, receivedQty=1, acceptedQty=1, rejectedQty=0),
        ],
    )
    order = details(client, "orders", order["id"])
    bill = create(
        client,
        h,
        "invoices",
        poId=order["id"],
        parentVersion=order["version"],
        invoiceNo="MIXED-BILL",
        dueDate="2027-12-31",
        items=[dict(lineIndex=0, quantity=5), dict(lineIndex=1, quantity=1)],
    )
    bill = action(client, h, "invoices", bill, "approve")
    with app.app_context():
        entry = db.session.scalar(
            select(JournalEntry).where(
                JournalEntry.source == "invoices:" + str(bill["id"])
            )
        )
        debits = {line.account: line.debit for line in entry.lines if line.debit}
        assert debits["2105"] == 50 and debits["6105"] == 50
    post(
        client,
        h,
        f'invoices/{bill["id"]}',
        {
            "version": bill["version"],
            "requestKey": "attempt-edit-posted-invoice",
            "amount": 1,
        },
        405,
    )


def test_migration_of_existing_posted_transactions_does_not_repost_ledgers(app):
    from backend import master_store

    client, h = session(app)
    product, vendor, customer = masters(client, h)
    order = purchase(client, h, product, vendor)
    order, _ = receive_bill_pay(client, h, order, 20, "MIGRATION-POSTED-BILL")
    with app.app_context():
        doc = db.session.get(Document, "app")
        original = deepcopy(doc.data)
        counts = (
            db.session.query(JournalEntry).count(),
            db.session.query(StockMove).count(),
        )
        # On-disk layout of the previous release: SQL masters, JSON transaction arrays.
        legacy = {k: v for k, v in original.items() if k not in master_store.MODELS}
        legacy[master_store.MARKER] = 1
        doc.stored_data = legacy
        db.session.query(store.RFQVendor).delete()
        for model in reversed(list(store.LINE_MODELS.values())):
            db.session.query(model).delete()
        for model in reversed(list(store.MODELS.values())):
            db.session.query(model).delete()
        db.session.commit()
    # init-db must not silently migrate before the verified migration command.
    runner = app.test_cli_runner()
    init = runner.invoke(args=["init-db"])
    assert init.exit_code == 0, init.output
    with app.app_context():
        assert store.MARKER not in db.session.get(Document, "app").stored_data
    assert client.get("/api/trade/orders").status_code == 503
    result = runner.invoke(args=["migrate-storage"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        doc = db.session.get(Document, "app")
        revision = doc.revision
        assert all(doc.data[key] == original[key] for key in store.SPECS)
        assert (
            db.session.query(JournalEntry).count(),
            db.session.query(StockMove).count(),
        ) == counts
    result = runner.invoke(args=["migrate-storage"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert db.session.get(Document, "app").revision == revision
    assert details(client, "orders", order["id"])["status"] == "Completed"


def test_legacy_extensions_and_unresolved_references_round_trip_without_fabrication(
    app,
):
    client, h = session(app)
    with app.app_context():
        doc = db.session.get(Document, "app")
        stored = deepcopy(doc.stored_data)
        stored.pop(store.MARKER)
        stored["orders"] = [
            dict(
                id="legacy-order",
                poNo="OLD-1",
                vendorId="not-an-existing-vendor",
                poDate="2026-01-01",
                status="Draft",
                total=1.23456789,
                custom={"retain": True},
                items=[
                    dict(
                        productId="missing-old-item",
                        productName="Historical item",
                        quantity=1,
                        rate=1.23456789,
                        total=1.23456789,
                    )
                ],
            )
        ]
        doc.stored_data = stored
        db.session.commit()
    migrated = app.test_cli_runner().invoke(args=["migrate-storage"])
    assert migrated.exit_code == 0, migrated.output
    with app.app_context():
        row = db.session.get(store.MODELS["orders"], "legacy-order")
        assert row.vendor_id is None and row.lines[0].product_id is None
        value = store.record("orders", row)
        assert value == stored["orders"][0]
        assert (
            row.extras["_tradeMeta"]["unresolved"]["vendorId"]
            == "not-an-existing-vendor"
        )
    # New commands cannot turn a historical dangling product into stock.
    value = details(client, "orders", "legacy-order")
    response = client.patch(
        "/api/trade/orders/legacy-order",
        headers=h,
        json={
            "version": value["version"],
            "requestKey": "repair-missing-product",
            "items": [dict(productId="missing-old-item", quantity=1, rate=1)],
        },
    )
    assert response.status_code == 404


def test_partial_invoice_rounding_conserves_original_order_cents(app):
    client, h = session(app)
    product, vendor, customer = masters(client, h)
    quote = create(
        client,
        h,
        "salesQuotations",
        customerId=customer["id"],
        items=[dict(productId=product["id"], quantity=7, rate=0.1, taxPercent=5)],
    )
    assert quote["total"] == 0.74 and quote["taxAmount"] == 0.04
    for step in ("submit", "approve", "send", "accept"):
        quote = action(client, h, "salesQuotations", quote, step)
    order = create(
        client,
        h,
        "salesOrders",
        quotationId=quote["id"],
        parentVersion=quote["version"],
    )
    amounts = []
    tax = []
    for index in range(7):
        order = details(client, "salesOrders", order["id"])
        invoice = create(
            client,
            h,
            "customerInvoices",
            orderId=order["id"],
            parentVersion=order["version"],
            dueDate="2027-12-31",
            items=[dict(lineIndex=0, quantity=1)],
        )
        amounts.append(Decimal(str(invoice["amount"])))
        tax.append(Decimal(str(invoice["taxAmount"])))
    assert sum(amounts) == Decimal("0.74") and sum(tax) == Decimal("0.04")


def test_requester_can_submit_demand_without_edit_permission(app):
    from backend.test_app import PASSWORD

    client, h = session(app)
    product, vendor, customer = masters(client, h)
    response = client.post(
        "/api/users",
        headers=h,
        json={
            "name": "Requester",
            "email": "requester@example.test",
            "password": PASSWORD,
            "role": "Requester",
            "active": True,
        },
    )
    assert response.status_code == 200
    requester = app.test_client()
    login = requester.post(
        "/api/auth/login",
        json={"email": "requester@example.test", "password": PASSWORD},
    )
    rh = {"X-CSRF-Token": login.json["csrfToken"]}
    demand = create(
        requester,
        rh,
        "requests",
        department="Office",
        items=[dict(productId=product["id"], quantity=1, rate=10)],
    )
    assert demand["status"] == "Pending Approval" and demand["actions"] == []
    post(
        requester,
        rh,
        f'requests/{demand["id"]}/actions/approve',
        {"version": demand["version"], "requestKey": "requester-self-approval"},
        403,
    )
    assert action(client, h, "requests", demand, "approve")["status"] == "Approved"


def test_large_amount_inputs_fail_validation_before_database_or_ledger_write(app):
    client, h = session(app)
    product, vendor, customer = masters(client, h)
    post(
        client,
        h,
        "salesQuotations",
        dict(
            customerId=customer["id"],
            requestKey="too-large-line-input",
            items=[dict(productId=product["id"], quantity=1e12, rate=1e12)],
        ),
        400,
    )
    assert client.get("/api/trade/salesQuotations").json["total"] == 0


def test_trade_sql_pagination_counts_and_print_access_are_scoped(app):
    from sqlalchemy import event

    client, h = session(app)
    product, vendor, customer = masters(client, h)
    app.config["ENABLE_LEGACY_TRADE_WRITES"] = True
    assert (
        patch(
            client,
            h,
            {
                "salesQuotations": [
                    dict(
                        id=i,
                        quotationNo=f"PAGE-{i:03}",
                        customerId=customer["id"],
                        customerName=customer["name"],
                        status="Draft",
                        ownerId="seller" if i < 31 else "admin",
                        total=10,
                        items=[
                            dict(productId=product["id"], quantity=1, rate=10, total=10)
                        ],
                    )
                    for i in range(60)
                ]
            },
        ).status_code
        == 200
    )
    app.config["ENABLE_LEGACY_TRADE_WRITES"] = False
    seller, sh = session(app, "seller")
    statements = []
    with app.app_context():
        engine = db.engine

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "trade_sales_quotation" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = seller.get("/api/trade/salesQuotations?page=2&pageSize=25").json
        assert result["total"] == 31 and len(result["items"]) == 6
        assert len(statements) == 2 and any("LIMIT" in sql for sql in statements)
        assert all("trade_sales_quotation_line" not in sql for sql in statements)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert seller.get("/api/trade/salesQuotations/59/print").status_code == 404
    assert seller.get("/api/trade/salesQuotations/0/print").status_code == 200
    # Same-manager team members can read Sales documents, but do not gain private lead notes.
    manager, _ = session(app, "manager")
    assert manager.get("/api/trade/salesQuotations").json["total"] == 31


def test_discounted_partial_receipts_and_bills_clear_grni_to_exact_line_cents(app):
    client, h = session(app)
    product, vendor, customer = masters(client, h)
    order = create(
        client,
        h,
        "orders",
        vendorId=vendor["id"],
        deliveryDate="2027-12-31",
        items=[
            dict(
                productId=product["id"],
                quantity=1000,
                rate=0.01,
                discountPercent=33.3333,
            )
        ],
    )
    assert order["total"] == 6.67
    for step in ("submit", "approve", "send"):
        order = action(client, h, "orders", order, step)
    for quantity in (300, 700):
        create(
            client,
            h,
            "receipts",
            poId=order["id"],
            parentVersion=order["version"],
            items=[
                dict(
                    lineIndex=0,
                    receivedQty=quantity,
                    acceptedQty=quantity,
                    rejectedQty=0,
                )
            ],
        )
        order = details(client, "orders", order["id"])
        bill = create(
            client,
            h,
            "invoices",
            poId=order["id"],
            parentVersion=order["version"],
            invoiceNo="CENT-" + str(quantity),
            dueDate="2027-12-31",
            items=[dict(lineIndex=0, quantity=quantity)],
        )
        bill = action(client, h, "invoices", bill, "approve")
        order = details(client, "orders", order["id"])
    stock = client.get("/api/erp/inventory").json["products"][0]
    assert Decimal(stock["value"]) == Decimal("6.67")
    report = client.get("/api/erp/reports").json
    assert (
        Decimal(next(a["balance"] for a in report["accounts"] if a["code"] == "2105"))
        == 0
    )
    with app.app_context():
        invoice = db.session.get(store.MODELS["invoices"], str(bill["id"]))
        order_row = db.session.get(store.MODELS["orders"], str(order["id"]))
        assert invoice.lines[0].source_line_id == order_row.lines[0].id
