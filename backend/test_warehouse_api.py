"""Stock ownership, backorder fulfillment and internal-transfer conservation."""

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
    post,
)
from backend.test_credit_api import returned
from backend.erp import StockBalance, JournalEntry, StockMove
from backend.app import db
from backend.warehouse_api import Reservation, LocationBalance, Backorder

n = 0


def call(c, h, command, data, expected=200):
    global n
    n += 1
    response = c.post(
        "/api/warehouse/commands/" + command,
        headers=h,
        json={"requestKey": "warehouse-test-" + str(n), **data},
    )
    assert response.status_code == expected, response.json
    return response.json.get("record")


def product(c, p):
    return c.get("/api/inventory/products/" + str(p["id"])).json["record"]


def sale(c, h, p, customer, qty=10):
    quote = create(
        c,
        h,
        "salesQuotations",
        customerId=customer["id"],
        items=[dict(productId=p["id"], quantity=qty, rate=20)],
    )
    for step in ("submit", "approve", "send", "accept"):
        quote = action(c, h, "salesQuotations", quote, step)
    return create(
        c, h, "salesOrders", quotationId=quote["id"], parentVersion=quote["version"]
    )


def transfer(c, h, p, source, target, qty, expected=200, **extra):
    state = product(c, p)
    return call(
        c,
        h,
        "transfer",
        dict(
            productId=str(p["id"]),
            fromLocation=source,
            toLocation=target,
            quantity=qty,
            reason="Warehouse test transfer",
            version=state["warehouseVersion"],
            **extra,
        ),
        expected,
    )


def test_competing_orders_reserve_once_and_sales_backorders_close(app):
    c, h = session(app)
    p, v, customer = masters(c, h)
    po = purchase(c, h, p, v)
    po, _ = receive_bill_pay(c, h, po, 12, "WAREHOUSE-PARTIAL")
    first = sale(c, h, p, customer)
    second = sale(c, h, p, customer)
    state = product(c, p)
    assert Decimal(state["reserved"]) == 12 and Decimal(state["available"]) == 0
    assert first["reservedQuantity"] == 10 and second["reservedQuantity"] == 2
    viewer, vh = session(app, "viewer")
    assert viewer.get("/api/warehouse/reservations").json["items"] == []

    transfer(c, h, p, "Stock", "Production", 1, 400)
    state = product(c, p)
    bad = c.post(
        "/api/inventory/commands/scrap",
        headers=h,
        json=dict(
            productId=p["id"],
            version=state["version"],
            quantity=1,
            reason="Reserved stock cannot scrap",
            requestKey="reserved-scrap-denied",
        ),
    )
    assert bad.status_code == 400, bad.json
    post(
        c,
        h,
        "deliveries",
        dict(
            orderId=second["id"],
            parentVersion=second["version"],
            items=[dict(lineIndex=0, deliveredQty=3)],
            requestKey="over-reservation-dispatch",
        ),
        400,
    )
    delivery = create(
        c,
        h,
        "deliveries",
        orderId=second["id"],
        parentVersion=second["version"],
        items=[dict(lineIndex=0, deliveredQty=2)],
    )
    action(c, h, "deliveries", delivery, "deliver")
    rows = c.get("/api/warehouse/backorders").json["items"]
    bo = next(r for r in rows if r["orderId"] == str(second["id"]))
    assert Decimal(bo["quantity"]) == 8 and bo["status"] == "Waiting Stock"
    create(
        c,
        h,
        "receipts",
        poId=po["id"],
        parentVersion=details(c, "orders", po["id"])["version"],
        items=[dict(lineIndex=0, receivedQty=8, acceptedQty=8, rejectedQty=0)],
    )
    second = action(
        c, h, "salesOrders", details(c, "salesOrders", second["id"]), "reserve"
    )
    assert second["reservedQuantity"] == 8
    ready = next(
        r
        for r in c.get("/api/warehouse/backorders").json["items"]
        if r["orderId"] == str(second["id"])
    )
    assert ready["status"] == "Ready"
    delivery = create(
        c,
        h,
        "deliveries",
        orderId=second["id"],
        parentVersion=second["version"],
        items=[dict(lineIndex=0, deliveredQty=8)],
    )
    assert bo["number"] in delivery["backorderReference"]
    action(c, h, "deliveries", delivery, "deliver")
    assert not [
        r
        for r in c.get("/api/warehouse/backorders").json["items"]
        if r["orderId"] == str(second["id"])
    ]
    first = action(
        c, h, "salesOrders", details(c, "salesOrders", first["id"]), "cancel"
    )
    assert first["reservationStatus"] == "Released"
    state = product(c, p)
    assert Decimal(state["reserved"]) == 0 and Decimal(state["available"]) == 10
    with app.app_context():
        assert (
            sum(
                db.session.scalars(
                    select(LocationBalance.quantity).where(
                        LocationBalance.product_id == str(p["id"])
                    )
                )
            )
            == db.session.get(StockBalance, str(p["id"])).quantity
        )


def test_internal_transfers_preserve_quantity_value_and_journals(app):
    c, h = session(app)
    p, _, _ = masters(c, h)
    current = product(c, p)
    r = c.post(
        "/api/inventory/commands/adjust",
        headers=h,
        json=dict(
            productId=p["id"],
            version=current["version"],
            quantity=10,
            unitCost=10,
            reason="Opening warehouse stock",
            requestKey="warehouse-opening",
        ),
    )
    assert r.status_code == 200, r.json
    with app.app_context():
        before = db.session.scalar(select(func.count()).select_from(JournalEntry))
    state = product(c, p)
    payload = dict(
        productId=str(p["id"]),
        fromLocation="Stock",
        toLocation="Production",
        quantity=4,
        reason="Production staging",
        version=state["warehouseVersion"],
        requestKey="transfer-idempotent",
    )
    first = call(c, h, "transfer", payload)
    retry = call(c, h, "transfer", payload)
    assert first == retry
    after = product(c, p)
    assert (
        Decimal(after["locations"]["Stock"]) == 6
        and Decimal(after["locations"]["Production"]) == 4
    )
    assert Decimal(after["quantity"]) == 10 and Decimal(after["value"]) == 100
    transfer(c, h, p, "Stock", "Production", 7, 400)
    transfer(c, h, p, "Stock", "Stock", 1, 400)
    call(c, h, "transfer", {**payload, "requestKey": "transfer-stale-version"}, 409)
    transfer(c, h, p, "Production", "Returns", 2)
    with app.app_context():
        assert (
            db.session.scalar(select(func.count()).select_from(JournalEntry)) == before
        )
    viewer, vh = session(app, "viewer")
    call(viewer, vh, "transfer", payload, 403)


def test_returned_goods_stay_quarantined_until_internal_transfer(app):
    c, h = session(app)
    p, v, customer = masters(c, h)
    po = purchase(c, h, p, v)
    po, _ = receive_bill_pay(c, h, po, 10, "RETURN-STOCK-BILL")
    order = sale(c, h, p, customer)
    delivery = create(
        c,
        h,
        "deliveries",
        orderId=order["id"],
        parentVersion=order["version"],
        items=[dict(lineIndex=0, deliveredQty=10)],
    )
    action(c, h, "deliveries", delivery, "deliver")
    returned(c, h, f'deliveries:{delivery["id"]}:0', 2)
    state = product(c, p)
    assert (
        Decimal(state["locations"]["Returns"]) == 2 and Decimal(state["available"]) == 0
    )
    order = details(c, "salesOrders", order["id"])
    assert order["reservationStatus"] == "Waiting Stock"
    post(
        c,
        h,
        "deliveries",
        dict(
            orderId=order["id"],
            parentVersion=order["version"],
            items=[dict(lineIndex=0, deliveredQty=1)],
            requestKey="quarantined-dispatch",
        ),
        400,
    )
    transfer(c, h, p, "Returns", "Stock", 2)
    order = action(
        c, h, "salesOrders", details(c, "salesOrders", order["id"]), "reserve"
    )
    assert order["reservedQuantity"] == 2
    replacement = create(
        c,
        h,
        "deliveries",
        orderId=order["id"],
        parentVersion=order["version"],
        items=[dict(lineIndex=0, deliveredQty=2)],
    )
    action(c, h, "deliveries", replacement, "deliver")
    assert Decimal(product(c, p)["quantity"]) == 0


def test_purchase_backorder_tracks_remaining_and_rejects_over_receipt(app):
    c, h = session(app)
    p, v, _ = masters(c, h)
    po = purchase(c, h, p, v)
    receipt = create(
        c,
        h,
        "receipts",
        poId=po["id"],
        parentVersion=po["version"],
        items=[dict(lineIndex=0, receivedQty=6, acceptedQty=6, rejectedQty=0)],
    )
    rows = c.get("/api/warehouse/backorders").json["items"]
    bo = next(r for r in rows if r["kind"] == "purchase")
    assert Decimal(bo["quantity"]) == 14 and bo["originDocument"] == str(receipt["id"])
    po = details(c, "orders", po["id"])
    post(
        c,
        h,
        "receipts",
        dict(
            poId=po["id"],
            parentVersion=po["version"],
            items=[dict(lineIndex=0, receivedQty=15, acceptedQty=15, rejectedQty=0)],
            requestKey="backorder-over-receipt",
        ),
        400,
    )
    receipt = create(
        c,
        h,
        "receipts",
        poId=po["id"],
        parentVersion=po["version"],
        items=[dict(lineIndex=0, receivedQty=14, acceptedQty=14, rejectedQty=0)],
    )
    assert bo["number"] in receipt["backorderReference"]
    assert not c.get("/api/warehouse/backorders").json["items"]


def test_upgrade_initializes_locations_without_reposting_stock(app):
    c, h = session(app)
    p, _, _ = masters(c, h)
    current = product(c, p)
    assert (
        c.post(
            "/api/inventory/commands/adjust",
            headers=h,
            json=dict(
                productId=p["id"],
                version=current["version"],
                quantity=5,
                unitCost=10,
                reason="Migration fixture",
                requestKey="warehouse-migration-stock",
            ),
        ).status_code
        == 200
    )
    with app.app_context():
        db.session.query(LocationBalance).delete()
        db.session.commit()
        before = db.session.scalar(select(func.count()).select_from(JournalEntry))
    for _ in range(2):
        r = app.test_cli_runner().invoke(args=["migrate-storage"])
        assert r.exit_code == 0, r.output
        state = product(c, p)
        assert (
            Decimal(state["locations"]["Stock"]) == 5 and Decimal(state["value"]) == 50
        )
        with app.app_context():
            assert (
                db.session.scalar(select(func.count()).select_from(JournalEntry))
                == before
            )


def test_production_uses_staging_and_cannot_consume_sales_reservations(app):
    from backend.test_production_api import (
        command as production,
        action as production_action,
    )

    c, h = session(app)
    raw, _, customer = masters(c, h)
    state = product(c, raw)
    assert (
        c.post(
            "/api/inventory/commands/adjust",
            headers=h,
            json=dict(
                productId=raw["id"],
                version=state["version"],
                quantity=10,
                unitCost=10,
                reason="Production test stock",
                requestKey="staging-stock",
            ),
        ).status_code
        == 200
    )
    transfer(c, h, raw, "Stock", "Production", 4)
    sale(c, h, raw, customer, 6)
    output = c.post(
        "/api/products",
        headers=h,
        json=dict(
            name="Staging output",
            sku="STAGING-OUTPUT",
            rate=10,
            requestKey="staging-output",
        ),
    ).json["record"]
    bom = production(
        c,
        h,
        "bom",
        name="Staging BOM",
        productId=output["id"],
        quantity=1,
        conversionCost=0,
        components=[dict(productId=raw["id"], quantity=5)],
    )
    order = production(
        c, h, "order", bomId=bom["id"], bomVersion=bom["version"], quantity=1
    )
    assert order["materialsAvailable"] is False

    order = production_action(c, h, order, "confirm")
    production_action(c, h, order, "complete", 400)
    # The failed operation retains its allocation until explicitly cancelled.
    production_action(c, h, order, "cancel")
    # A smaller operation may consume released staging without touching reserved Stock.
    bom = production(
        c,
        h,
        "bom",
        name="Smaller staging BOM",
        productId=output["id"],
        quantity=1,
        conversionCost=0,
        components=[dict(productId=raw["id"], quantity=4)],
    )
    order = production(
        c, h, "order", bomId=bom["id"], bomVersion=bom["version"], quantity=1
    )
    order = production_action(c, h, order, "confirm")
    production_action(c, h, order, "complete")
    current = product(c, raw)
    assert (
        Decimal(current["locations"]["Stock"]) == 6
        and Decimal(current["reserved"]) == 6
        and Decimal(current["locations"]["Production"]) == 0
    )


def test_concurrent_confirmations_cannot_double_reserve_stock(app):
    from concurrent.futures import ThreadPoolExecutor

    c, h = session(app)
    p, _, customer = masters(c, h)
    state = product(c, p)
    assert (
        c.post(
            "/api/inventory/commands/adjust",
            headers=h,
            json=dict(
                productId=p["id"],
                version=state["version"],
                quantity=12,
                unitCost=10,
                reason="Concurrent reservation stock",
                requestKey="concurrent-res-stock",
            ),
        ).status_code
        == 200
    )
    quotes = []
    for _ in range(2):
        quote = create(
            c,
            h,
            "salesQuotations",
            customerId=customer["id"],
            items=[dict(productId=p["id"], quantity=10, rate=10)],
        )
        for step in ("submit", "approve", "send", "accept"):
            quote = action(c, h, "salesQuotations", quote, step)
        quotes.append(quote)

    def confirm(index):
        client, headers = session(app)
        for _ in range(3):
            response = client.post(
                "/api/trade/salesOrders",
                headers=headers,
                json=dict(
                    quotationId=quotes[index]["id"],
                    parentVersion=quotes[index]["version"],
                    requestKey="parallel-reservation-" + str(index),
                ),
            )
            if response.status_code != 503:
                break
        assert response.status_code == 200, response.json
        return response.json["record"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        orders = list(executor.map(confirm, range(2)))
    assert sum(o["reservedQuantity"] for o in orders) == 12
    assert sorted(o["reservedQuantity"] for o in orders) == [2, 10]
    assert Decimal(product(c, p)["available"]) == 0


def test_releasing_reservation_frees_stock_and_requires_availability_check(app):
    c, h = session(app)
    p, _, customer = masters(c, h)
    current = product(c, p)
    assert (
        c.post(
            "/api/inventory/commands/adjust",
            headers=h,
            json=dict(
                productId=p["id"],
                version=current["version"],
                quantity=10,
                unitCost=10,
                reason="Releasable stock",
                requestKey="release-stock",
            ),
        ).status_code
        == 200
    )
    order = sale(c, h, p, customer)
    order = action(c, h, "salesOrders", order, "unreserve")
    assert order["reservedQuantity"] == 0 and Decimal(product(c, p)["available"]) == 10
    post(
        c,
        h,
        "deliveries",
        dict(
            orderId=order["id"],
            parentVersion=order["version"],
            items=[dict(lineIndex=0, deliveredQty=1)],
            requestKey="paused-delivery-denied",
        ),
        400,
    )
    order = action(c, h, "salesOrders", order, "reserve")
    assert order["reservedQuantity"] == 10


def test_open_stock_obligations_prevent_changing_product_to_service(app):
    c, h = session(app)
    p, _, customer = masters(c, h)
    order = sale(c, h, p, customer)
    denied = c.patch(
        "/api/products/" + str(p["id"]),
        headers=h,
        json=dict(version=p["version"], productType="service"),
    )
    assert denied.status_code == 400, denied.json
    action(c, h, "salesOrders", order, "cancel")
    allowed = c.patch(
        "/api/products/" + str(p["id"]),
        headers=h,
        json=dict(version=p["version"], productType="service"),
    )
    assert allowed.status_code == 200, allowed.json
