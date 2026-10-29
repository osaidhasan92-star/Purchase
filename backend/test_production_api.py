"""Production conservation, snapshot, privacy and atomic posting simulations."""

from decimal import Decimal
from copy import deepcopy
import pytest
from sqlalchemy import select, func, event
from backend.test_app import app, session
from backend.test_inventory_api import make_product, adjust, product
from backend.app import db, Document
from backend.erp import (
    ManufacturingOrder,
    StockMove,
    JournalEntry,
    JournalLine,
    StockBalance,
)

counter = 0


def command(c, h, kind, expected=200, **data):
    global counter
    counter += 1
    r = c.post(
        "/api/production/commands/" + kind,
        headers=h,
        json={"requestKey": "production-test-" + str(counter), **data},
    )
    assert r.status_code == expected, r.json
    return r.json.get("record")


def setup(c, h):
    raw = make_product(c, h, "Production raw")
    second = make_product(c, h, "Production second")
    output = make_product(c, h, "Production finished")
    b = command(
        c,
        h,
        "bom",
        name="Native BoM",
        productId=output,
        quantity=2,
        conversionCost=5,
        components=[
            dict(productId=raw, quantity=2),
            dict(productId=second, quantity=1),
        ],
    )
    return raw, second, output, b


def order(c, h, b, quantity=2):
    return command(
        c,
        h,
        "order",
        bomId=b["id"],
        bomVersion=b["version"],
        quantity=quantity,
        date="2026-10-28",
    )


def action(c, h, o, act, expected=200, **extra):
    return command(c, h, act, expected, id=o["id"], version=o["version"], **extra)


def detail(c, o):
    return c.get("/api/production/orders/" + str(o["id"])).json["record"]


def total(c):
    return c.get("/api/finance/summary").json


def test_complete_production_stock_cost_wip_and_retry(app):
    c, h = session(app)
    raw, second, out, b = setup(c, h)
    adjust(c, h, raw, 20, 10)
    adjust(c, h, second, 10, 3)
    o = order(c, h, b, 4)
    assert o["components"][0]["quantity"] == "4.0000"
    assert o["conversionCost"] == "10.00"
    assert o["materialsAvailable"]
    o = action(c, h, o, "confirm")
    o = action(c, h, o, "start")
    data = dict(id=o["id"], version=o["version"], requestKey="complete-repeat-key")
    done = command(c, h, "complete", **data)
    assert done["state"] == "Done" and Decimal(done["actualCost"]) == 56
    assert command(c, h, "complete", **data)["id"] == done["id"]
    assert (
        Decimal(product(c, raw)["quantity"]) == 16
        and Decimal(product(c, second)["quantity"]) == 8
    )
    assert (
        Decimal(product(c, out)["quantity"]) == 4
        and Decimal(product(c, out)["value"]) == 56
    )
    with app.app_context():
        entries = db.session.scalars(
            select(JournalEntry).where(
                JournalEntry.source.like("%mo:" + str(o["id"]) + ":%")
            )
        ).all()
        assert len(entries) == 4
        journal_id = entries[0].id
        assert (
            db.session.scalar(
                select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                    JournalLine.account == "1250"
                )
            )
            == 0
        )
        assert (
            db.session.scalar(
                select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                    JournalLine.account == "2400"
                )
            )
            == 10
        )
        for e in entries:
            assert sum(l.debit for l in e.lines) == sum(l.credit for l in e.lines)
    assert Decimal(total(c)["balanceCheck"]) == 0
    assert c.get("/api/production/orders/" + str(o["id"]) + "/print").status_code == 200
    assert done["journalHref"] and done["movementsHref"]
    source = c.get("/api/finance/entries/" + str(journal_id)).json["record"][
        "sourceLink"
    ]
    assert source["href"] == "/api/production/orders/" + str(o["id"]) + "/print"


def test_bom_validation_and_stock_product_references(app):
    c, h = session(app)
    raw, second, out, b = setup(c, h)
    service = make_product(c, h, "Production service", "service")
    base = dict(name="Bad BoM", productId=out, quantity=1, conversionCost=0)
    for rows in (
        [],
        [dict(productId=out, quantity=1)],
        [dict(productId=raw, quantity=1)] * 2,
        [dict(productId=service, quantity=1)],
        [dict(productId=raw, quantity=0)],
    ):
        command(c, h, "bom", 400, **base, components=rows)
    command(
        c,
        h,
        "bom",
        400,
        **{**base, "productId": service},
        components=[dict(productId=raw, quantity=1)]
    )
    command(
        c,
        h,
        "bom",
        400,
        **{**base, "conversionCost": -1},
        components=[dict(productId=raw, quantity=1)]
    )
    command(
        c,
        h,
        "bom",
        400,
        **base,
        components=[dict(productId=raw, quantity=1)],
        status="Approved"
    )
    command(c, h, "order", 400, bomId=b["id"], bomVersion=b["version"], quantity=0)
    assert c.get("/api/production/orders/999999999999999999999").status_code == 404


def test_bom_edit_preserves_existing_order_snapshot(app):
    c, h = session(app)
    raw, second, out, b = setup(c, h)
    old = order(c, h, b)
    updated = command(
        c,
        h,
        "edit-bom",
        id=b["id"],
        version=b["version"],
        name="Revised BoM",
        quantity=2,
        conversionCost=10,
        components=[
            dict(productId=raw, quantity=5),
            dict(productId=second, quantity=3),
        ],
    )
    command(c, h, "order", 409, bomId=b["id"], bomVersion=b["version"], quantity=2)
    current = order(c, h, updated)
    old = detail(c, old)
    assert (
        old["components"][0]["quantity"] == "2.0000" and old["conversionCost"] == "5.00"
    )
    assert (
        current["components"][0]["quantity"] == "5.0000"
        and current["conversionCost"] == "10.00"
    )
    command(
        c,
        h,
        "edit-bom",
        409,
        id=b["id"],
        version=b["version"],
        name="Stale",
        quantity=2,
        components=[dict(productId=raw, quantity=1)],
    )
    command(
        c,
        h,
        "edit-bom",
        400,
        id=b["id"],
        version=updated["version"],
        name="Wrong product",
        quantity=2,
        components=[dict(productId=raw, quantity=1)],
        productId=second,
    )


def test_shortage_rolls_back_earlier_component_and_all_journals(app):
    c, h = session(app)
    raw, second, out, b = setup(c, h)
    adjust(c, h, raw, 10, 10)
    o = action(c, h, order(c, h, b), "confirm")
    assert not o["materialsAvailable"]
    with app.app_context():
        before = (
            db.session.scalar(select(func.count()).select_from(StockMove)),
            db.session.scalar(select(func.count()).select_from(JournalEntry)),
        )
    action(c, h, o, "complete", 400)
    with app.app_context():
        assert before == (
            db.session.scalar(select(func.count()).select_from(StockMove)),
            db.session.scalar(select(func.count()).select_from(JournalEntry)),
        )
    assert (
        Decimal(product(c, raw)["quantity"]) == 10
        and Decimal(product(c, out)["quantity"]) == 0
    )
    assert detail(c, o)["state"] == "Confirmed"
    adjust(c, h, second, 2, 3)
    action(c, h, o, "complete", 409)
    assert action(c, h, detail(c, o), "complete")["state"] == "Done"


def test_transitions_versions_keys_cancellation_and_period_lock(app):
    c, h = session(app)
    raw, second, out, b = setup(c, h)
    o = order(c, h, b)
    action(c, h, o, "start", 409)
    action(c, h, o, "complete", 409)
    command(c, h, "confirm", 428, id=o["id"])
    cancelled = action(c, h, o, "cancel")
    assert cancelled["state"] == "Cancelled"
    action(c, h, cancelled, "confirm", 409)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(StockMove)) == 0
    data = dict(
        bomId=b["id"],
        bomVersion=b["version"],
        quantity=2,
        date="2026-10-28",
        requestKey="order-key-repeat",
    )
    o = command(c, h, "order", **data)
    assert command(c, h, "order", **data)["id"] == o["id"]
    command(c, h, "order", 409, **{**data, "quantity": 4})
    adjust(c, h, raw, 4)
    adjust(c, h, second, 4)
    o = action(c, h, detail(c, o), "confirm")
    lock = c.get("/api/finance/period-lock").json["record"]
    r = c.post(
        "/api/finance/commands/period-lock",
        headers=h,
        json=dict(
            version=lock["version"],
            date="2026-10-28",
            requestKey="production-lock-test",
        ),
    )
    assert r.status_code == 200
    action(c, h, o, "complete", 400)
    assert detail(c, o)["state"] == "Confirmed"
    assert Decimal(product(c, out)["quantity"]) == 0


def test_permissions_company_records_export_and_no_aggregate_projection(
    app, monkeypatch
):
    c, h = session(app)
    raw, second, out, b = setup(c, h)
    adjust(c, h, raw, 10)
    adjust(c, h, second, 10)
    o = order(c, h, b)
    viewer, vh = session(app, "viewer")
    assert viewer.get("/api/production/summary").status_code == 403
    with app.app_context():
        doc = db.session.get(Document, "app")
        s = deepcopy(doc.data)
        s["roles"]["Viewer"]["permissions"]["manufacturing"] = dict(
            view=True, create=False, edit=False, approve=False, export=False
        )
        doc.data = s
        db.session.commit()
    assert viewer.get("/api/production/orders/" + str(o["id"])).status_code == 200
    assert (
        viewer.get("/api/production/orders/" + str(o["id"]) + "/print").status_code
        == 403
    )
    action(viewer, vh, o, "confirm", 403)
    original = Document.data

    def blocked(self):
        if self.name in ("app", "hr"):
            raise AssertionError("Native production must not project app/HR registers")
        return original.fget(self)

    monkeypatch.setattr(Document, "data", property(blocked, original.fset))
    for path in ("summary", "products", "boms", "orders"):
        assert c.get("/api/production/" + path).status_code == 200
    o = action(c, h, o, "confirm")
    assert o["state"] == "Confirmed"
    assert action(c, h, o, "complete")["state"] == "Done"


def test_sql_header_pagination_search_and_print_escaping(app):
    c, h = session(app)
    raw, second, out, b = setup(c, h)
    for _ in range(3):
        order(c, h, b)
    with app.app_context():
        statements = []

        def trace(conn, cursor, sql, parameters, context, executemany):
            statements.append(sql)

        event.listen(db.engine, "before_cursor_execute", trace)
        try:
            page = c.get("/api/production/orders?pageSize=1&page=2").json
            assert (
                page["total"] == 3
                and len(page["items"]) == 1
                and "components" not in page["items"][0]
            )
            assert not any(
                "SELECT production_component.id" in sql for sql in statements
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", trace)
    assert c.get("/api/production/boms?search=NoMatch").json["total"] == 0
    assert (
        c.get("/api/production/orders?from=2026-11-01&to=2026-10-01").status_code == 400
    )
    assert c.get("/api/production/products?pageSize=101").status_code == 400
    b = command(
        c,
        h,
        "edit-bom",
        id=b["id"],
        version=b["version"],
        name="<script>BoM</script>",
        quantity=2,
        conversionCost=0,
        components=[dict(productId=raw, quantity=1)],
    )
    o = order(c, h, b)
    html = c.get("/api/production/orders/" + str(o["id"]) + "/print").text
    assert "&lt;script&gt;BoM&lt;/script&gt;" in html and "<script>BoM" not in html


def test_fractional_cost_and_upgrade_no_reposting(app):
    c, h = session(app)
    raw = make_product(c, h, "Tiny input")
    out = make_product(c, h, "Tiny output")
    adjust(c, h, raw, 3, 0.3333)
    b = command(
        c,
        h,
        "bom",
        name="Tiny cost BoM",
        productId=out,
        quantity=1,
        conversionCost=0.01,
        components=[dict(productId=raw, quantity=3)],
    )
    o = action(c, h, order(c, h, b, 1), "confirm")
    o = action(c, h, o, "complete")
    assert Decimal(o["actualCost"]) == Decimal("1.01")
    assert Decimal(product(c, raw)["value"]) == 0 and Decimal(
        product(c, out)["value"]
    ) == Decimal("1.01")
    with app.app_context():
        before = db.session.scalar(select(func.count()).select_from(JournalEntry))
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    assert detail(c, o)["state"] == "Done"
    with app.app_context():
        assert (
            db.session.scalar(select(func.count()).select_from(JournalEntry)) == before
        )


def test_large_shortage_estimate_does_not_fail_after_order_commit(app):
    c, h = session(app)
    raw, second, out, b = setup(c, h)
    adjust(c, h, raw, 1, 1000000000000)
    o = order(c, h, b, 100000000000)
    assert o["state"] == "Draft" and not o["materialsAvailable"]
    assert Decimal(o["estimatedCost"]) > Decimal("1000000000000")
    assert detail(c, o)["id"] == o["id"]
