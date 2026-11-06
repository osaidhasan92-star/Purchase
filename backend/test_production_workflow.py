"""Actual production, allocation isolation, linked remainders and ledger conservation."""

from decimal import Decimal
from sqlalchemy import select, func
from backend.test_app import app, session
from backend.test_production_api import setup, order, action, detail, command
from backend.test_inventory_api import adjust, product
from backend.app import db
from backend.erp import JournalEntry, JournalLine, StockMove, StockBalance
from backend.production_workflow import (
    MaterialReservation,
    ProductionResult,
    initialize,
)


def test_reservations_staging_competition_and_release(app):
    c, h = session(app)
    raw, second, out, bom = setup(c, h)
    adjust(c, h, raw, 5, 10)
    adjust(c, h, second, 3, 4)
    first = action(c, h, order(c, h, bom, 4), "confirm")
    assert Decimal(first["components"][0]["reserved"]) == 4
    competitor = action(c, h, order(c, h, bom, 4), "confirm")
    assert Decimal(competitor["components"][0]["reserved"]) == 1
    assert competitor["materialsAvailable"] is False
    before = product(c, raw)
    first = action(c, h, detail(c, first), "stage")
    assert Decimal(first["components"][0]["staged"]) == 4
    after = product(c, raw)
    assert after["quantity"] == before["quantity"] and after["value"] == before["value"]
    # Generic warehouse transfers cannot take another order's staged allocation.
    r = c.post(
        "/api/warehouse/commands/transfer",
        headers=h,
        json=dict(
            productId=raw,
            version=after["warehouseVersion"],
            fromLocation="Production",
            toLocation="Stock",
            quantity=1,
            reason="Cannot steal staging",
            requestKey="cannot-steal-staged",
        ),
    )
    assert r.status_code == 400
    action(c, h, detail(c, competitor), "complete", 400)
    action(c, h, detail(c, first), "cancel")
    competitor = action(c, h, detail(c, competitor), "reserve")
    assert competitor["materialsAvailable"] is True
    assert Decimal(competitor["components"][0]["reserved"]) == 4
    action(c, h, competitor, "complete")
    assert Decimal(product(c, raw)["quantity"]) == 1


def test_partial_actual_scrap_backorder_and_wip(app):
    c, h = session(app)
    raw, second, out, bom = setup(c, h)
    adjust(c, h, raw, 20, 10)
    adjust(c, h, second, 10, 3)
    original = action(c, h, order(c, h, bom, 4), "confirm")
    staged = action(c, h, original, "stage")
    original = action(c, h, staged, "start")
    payload = dict(
        id=original["id"],
        version=original["version"],
        producedQuantity=1,
        conversionCost=4,
        components=[
            dict(productId=raw, quantity="1.2", scrap=".3"),
            dict(productId=second, quantity=".6", scrap=".1"),
        ],
        requestKey="partial-actual-replay",
    )
    first = command(c, h, "complete", **payload)
    assert first["state"] == "Done" and Decimal(first["quantity"]) == 1
    assert Decimal(first["actualCost"]) == Decimal("17.80")
    assert Decimal(first["productionResult"]["scrapCost"]) == Decimal("3.30")
    assert Decimal(product(c, out)["value"]) == Decimal("17.80")
    assert Decimal(product(c, raw)["quantity"]) == Decimal("18.5")
    child_id = first["productionResult"]["backorderId"]
    child = c.get("/api/production/orders/" + str(child_id)).json["record"]
    assert Decimal(child["quantity"]) == 3 and child["state"] == "Confirmed"
    assert child["parentOrder"]["id"] == first["id"]
    assert Decimal(child["components"][0]["quantity"]) == 3
    assert Decimal(child["conversionCost"]) == Decimal("7.50")
    before = product(c, out)
    assert command(c, h, "complete", **payload)["id"] == first["id"]
    assert product(c, out)["quantity"] == before["quantity"]
    command(c, h, "complete", 409, **{**payload, "conversionCost": 5})
    child = action(c, h, child, "complete")
    assert child["state"] == "Done"
    assert Decimal(product(c, out)["quantity"]) == 4
    assert Decimal(product(c, out)["value"]) == Decimal("59.80")
    with app.app_context():
        assert (
            db.session.scalar(
                select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                    JournalLine.account == "1250"
                )
            )
            == 0
        )
        assert db.session.scalar(
            select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                JournalLine.account == "5105"
            )
        ) == Decimal(
            "-226.70"
        )  # opening adjustment credits 230; scrap debit 3.30
        assert db.session.scalar(select(func.sum(MaterialReservation.quantity))) == 0
        for entry in db.session.scalars(select(JournalEntry)):
            assert sum(line.debit for line in entry.lines) == sum(
                line.credit for line in entry.lines
            )


def test_invalid_actuals_atomic_failure_and_permissions(app):
    c, h = session(app)
    raw, second, out, bom = setup(c, h)
    adjust(c, h, raw, 4, 10)
    adjust(c, h, second, 2, 3)
    current = action(c, h, order(c, h, bom), "confirm")
    for data in [
        dict(producedQuantity=3),
        dict(producedQuantity=0),
        dict(conversionCost=-1),
        dict(components=[]),
        dict(components=[dict(productId=raw, quantity=1, scrap=-1)]),
        dict(
            components=[
                dict(productId=raw, quantity=1, scrap=0),
                dict(productId=raw, quantity=1, scrap=0),
            ]
        ),
    ]:
        action(c, h, current, "complete", 400, **data)
    # First material write and journal roll back if the second material is unavailable.
    before = product(c, raw)
    action(
        c,
        h,
        current,
        "complete",
        400,
        components=[
            dict(productId=raw, quantity=1, scrap=0),
            dict(productId=second, quantity=3, scrap=0),
        ],
    )
    assert product(c, raw)["quantity"] == before["quantity"]
    assert product(c, raw)["value"] == before["value"]
    assert detail(c, current)["state"] == "Confirmed"
    viewer, vh = session(app, "viewer")
    action(viewer, vh, current, "stage", 403)
    action(viewer, vh, current, "reserve", 403)
    action(viewer, vh, current, "complete", 403)
    assert action(c, h, current, "complete")["state"] == "Done"


def test_reservation_migration_preserves_existing_postings(app):
    c, h = session(app)
    raw, second, out, bom = setup(c, h)
    adjust(c, h, raw, 8, 10)
    adjust(c, h, second, 4, 3)
    done = action(c, h, action(c, h, order(c, h, bom), "confirm"), "complete")
    active = action(c, h, order(c, h, bom), "confirm")
    with app.app_context():
        db.session.query(MaterialReservation).delete()
        db.session.commit()
        counts = (
            db.session.scalar(select(func.count()).select_from(StockMove)),
            db.session.scalar(select(func.count()).select_from(JournalEntry)),
        )
        upgrade = app.test_cli_runner().invoke(args=["migrate-storage"])
        assert upgrade.exit_code == 0, upgrade.output
        initialize()
        db.session.commit()
        assert counts == (
            db.session.scalar(select(func.count()).select_from(StockMove)),
            db.session.scalar(select(func.count()).select_from(JournalEntry)),
        )
        assert (
            db.session.scalar(
                select(func.sum(MaterialReservation.quantity)).where(
                    MaterialReservation.order_id == active["id"]
                )
            )
            == 3
        )
    assert detail(c, done)["state"] == "Done"


def test_purchase_to_production_to_sale_and_payment(app):
    from backend.test_trade_api import (
        masters,
        purchase,
        receive_bill_pay,
        create,
        details,
        action as trade_action,
    )
    from backend.test_warehouse_api import sale

    c, h = session(app)
    raw, vendor, customer = masters(c, h)
    po = purchase(c, h, raw, vendor)
    receive_bill_pay(c, h, po, 20, "MANUFACTURING-E2E-RAW")
    output = c.post(
        "/api/products",
        headers=h,
        json=dict(
            name="End to end finished",
            sku="E2E-FIN",
            rate=50,
            requestKey="production-e2e-product",
        ),
    ).json["record"]
    bom = command(
        c,
        h,
        "bom",
        name="End to end BoM",
        productId=output["id"],
        quantity=1,
        conversionCost=5,
        components=[dict(productId=raw["id"], quantity=2)],
    )
    mo = action(c, h, order(c, h, bom, 2), "confirm")
    mo = action(c, h, mo, "stage")
    mo = action(c, h, mo, "start")
    mo = action(c, h, mo, "complete")
    assert Decimal(mo["actualCost"]) == 50
    so = sale(c, h, output, customer, 2)
    delivery = create(
        c,
        h,
        "deliveries",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, deliveredQty=2)],
    )
    trade_action(c, h, "deliveries", delivery, "deliver")
    so = details(c, "salesOrders", so["id"])
    invoice = create(
        c,
        h,
        "customerInvoices",
        dueDate="2027-12-31",
        orderId=so["id"],
        parentVersion=so["version"],
        items=[dict(lineIndex=0, quantity=2)],
    )
    invoice = trade_action(c, h, "customerInvoices", invoice, "submit")
    invoice = trade_action(c, h, "customerInvoices", invoice, "post")
    create(
        c,
        h,
        "customerPayments",
        invoiceId=invoice["id"],
        parentVersion=invoice["version"],
        amount=invoice["balance"],
        method="Cash",
    )
    invoice = details(c, "customerInvoices", invoice["id"])
    assert invoice["balance"] == 0 and invoice["status"] == "Paid"
    assert Decimal(product(c, output["id"])["quantity"]) == 0
    assert Decimal(product(c, raw["id"])["quantity"]) == 16
    assert Decimal(c.get("/api/finance/summary").json["balanceCheck"]) == 0


def test_waiting_manufacturing_prevents_service_conversion(app):
    c, h = session(app)
    raw, second, out, bom = setup(c, h)
    current = action(c, h, order(c, h, bom), "confirm")
    p = c.get("/api/products/" + str(raw)).json["record"]
    assert (
        c.patch(
            "/api/products/" + str(raw),
            headers=h,
            json=dict(version=p["version"], productType="service"),
        ).status_code
        == 400
    )
    action(c, h, current, "cancel")
    assert (
        c.patch(
            "/api/products/" + str(raw),
            headers=h,
            json=dict(version=p["version"], productType="service"),
        ).status_code
        == 200
    )


def test_legacy_actions_share_manufacturing_allocations(app):
    c, h = session(app)
    raw, second, out, bom = setup(c, h)
    adjust(c, h, raw, 4, 10)
    adjust(c, h, second, 2, 3)
    current = order(c, h, bom)
    endpoint = "/api/erp/manufacturing/" + str(current["id"])
    confirmed = c.post(endpoint + "/confirm", headers=h, json={})
    assert confirmed.status_code == 200, confirmed.json
    current = detail(c, current)
    assert Decimal(current["components"][0]["reserved"]) == 2
    assert c.post(endpoint + "/cancel", headers=h, json={}).status_code == 200
    assert Decimal(detail(c, current)["components"][0]["reserved"]) == 0
