"""Native stock simulations: quantity, value, ledger, concurrency and access."""

from decimal import Decimal
from copy import deepcopy
import pytest
from sqlalchemy import select, func
from backend.test_app import app, session
from backend.app import db, Document
from backend.erp import StockMove, StockBalance, JournalEntry, JournalLine, stock_move
from flask import g

counter = 0


def command(c, h, kind, **data):
    global counter
    counter += 1
    expected = data.pop("expected", 200)
    r = c.post(
        "/api/inventory/commands/" + kind,
        headers=h,
        json={"requestKey": "inventory-test-" + str(counter), **data},
    )
    assert r.status_code == expected, r.json
    return r.json.get("record")


def make_product(c, h, name="Native stock", kind="stock"):
    r = c.post(
        "/api/products",
        headers=h,
        json={
            "name": name,
            "sku": "STOCK-" + name.replace(" ", "-"),
            "productType": kind,
            "unit": "Each",
            "rate": 10,
            "requestKey": "product-"
            + __import__("hashlib").sha256(name.encode()).hexdigest(),
        },
    )
    assert r.status_code == 200, r.json
    return r.json["record"]["id"]


def product(c, p):
    return c.get("/api/inventory/products/" + str(p)).json["record"]


def adjust(c, h, p, quantity, cost=10, **extra):
    return command(
        c,
        h,
        "adjust",
        productId=p,
        version=product(c, p)["version"],
        quantity=quantity,
        unitCost=cost,
        date="2026-10-28",
        reason="Physical stock count",
        **extra
    )


def detail(c, m):
    return c.get("/api/inventory/movements/" + str(m["id"])).json["record"]


def source_move(app, p, qty, value, source, kind):
    with app.test_request_context():
        from backend.app import User

        g.user = db.session.get(User, "admin")
        m = stock_move(
            p,
            Decimal(str(qty)),
            source,
            kind,
            "2105" if qty > 0 else "5100",
            Decimal(str(value)) / Decimal(str(qty)) if qty > 0 else None,
            "2026-10-28",
            total_value=Decimal(str(value)) if qty > 0 else None,
        )
        db.session.commit()
        return m.id


def test_adjust_scrap_and_accounting_tieout(app):
    c, h = session(app)
    p = make_product(c, h)
    incoming = adjust(c, h, p, 10, 12.5)
    assert Decimal(incoming["value"]) == 125
    scrap = command(
        c,
        h,
        "scrap",
        productId=p,
        version=product(c, p)["version"],
        quantity=2,
        date="2026-10-28",
        reason="Damaged units",
    )
    assert Decimal(scrap["quantity"]) == -2 and Decimal(scrap["value"]) == -25
    outgoing = adjust(c, h, p, -1)
    assert Decimal(outgoing["value"]) == Decimal("-12.50")
    final = product(c, p)
    assert Decimal(final["quantity"]) == 7 and Decimal(final["value"]) == Decimal(
        "87.50"
    )
    report = c.get("/api/finance/summary").json
    assert Decimal(report["balanceCheck"]) == 0
    with app.app_context():
        moves = db.session.scalars(select(StockMove)).all()
        balance = db.session.get(StockBalance, p)
        assert (
            sum(m.value for m in moves) == balance.value
            and sum(m.quantity for m in moves) == balance.quantity
        )
        ledger = db.session.scalar(
            select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                JournalLine.account == "1200"
            )
        )
        assert ledger == balance.value
        for e in db.session.scalars(select(JournalEntry)):
            assert sum(l.debit for l in e.lines) == sum(l.credit for l in e.lines)
    assert detail(c, incoming)["reason"] == "Physical stock count"
    assert detail(c, incoming)["journalHref"].startswith(
        "erp.html?view=journals&source=stock:"
    )


def test_versions_idempotency_and_payload_collision(app):
    c, h = session(app)
    p = make_product(c, h)
    initial = product(c, p)
    data = dict(
        productId=p,
        version=initial["version"],
        quantity=5,
        unitCost=10,
        reason="Count",
        requestKey="same-stock-request",
    )
    a = command(c, h, "adjust", **data)
    b = command(c, h, "adjust", **data)
    assert a["id"] == b["id"]
    command(c, h, "adjust", **{**data, "quantity": 6}, expected=409)
    command(
        c,
        h,
        "adjust",
        productId=p,
        version=initial["version"],
        quantity=1,
        unitCost=10,
        reason="Stale",
        expected=409,
    )
    command(
        c,
        h,
        "adjust",
        productId=p,
        quantity=1,
        unitCost=10,
        reason="Missing version",
        expected=428,
    )
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(StockMove)) == 1


def test_negative_stock_service_zero_invalid_and_period_lock(app):
    c, h = session(app)
    p = make_product(c, h)
    service = make_product(c, h, "Consulting", "service")
    for q in (0, -1, "NaN", True, 1e13):
        adjust(c, h, p, q, expected=400)
    adjust(c, h, service, 1, expected=400)
    adjust(c, h, p, 1, -1, expected=400)
    command(
        c,
        h,
        "scrap",
        productId=p,
        version=product(c, p)["version"],
        quantity=-1,
        reason="Invalid",
        expected=400,
    )
    command(
        c,
        h,
        "adjust",
        productId=p,
        version=product(c, p)["version"],
        quantity=1,
        reason="Forged",
        value=999,
        expected=400,
    )
    lock = c.get("/api/finance/period-lock").json["record"]
    r = c.post(
        "/api/finance/commands/period-lock",
        headers=h,
        json=dict(
            date="2026-10-28", version=lock["version"], requestKey="inventory-lock-test"
        ),
    )
    assert r.status_code == 200
    adjust(c, h, p, 1, expected=400)
    assert Decimal(product(c, p)["quantity"]) == 0
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(StockMove)) == 0


def test_customer_partial_returns_recover_all_original_cents(app):
    c, h = session(app)
    p = make_product(c, h)
    source_move(app, p, 3, 1, "receipts:tiny:0", "Purchase Receipt")
    delivery = source_move(app, p, -3, 0, "deliveries:tiny:0", "Sales Delivery")
    original = c.get("/api/inventory/movements/" + str(delivery)).json["record"]
    values = []
    for n in range(3):
        r = command(
            c,
            h,
            "return",
            moveId=original["id"],
            version=original["version"],
            quantity=1,
            reason="Customer returned one unit",
        )
        values.append(Decimal(r["value"]))
        original = detail(c, original)
    assert sum(values) == 1 and values == [
        Decimal(".33"),
        Decimal(".34"),
        Decimal(".33"),
    ]
    assert Decimal(original["returnRemaining"]) == 0 and not original["canReturn"]
    command(
        c,
        h,
        "return",
        moveId=original["id"],
        version=original["version"],
        quantity=1,
        reason="Excess",
        expected=400,
    )
    assert (
        Decimal(product(c, p)["quantity"]) == 3 and Decimal(product(c, p)["value"]) == 1
    )


def test_vendor_return_uses_current_average_and_stale_limits(app):
    c, h = session(app)
    p = make_product(c, h)
    receipt = source_move(app, p, 10, 100, "receipts:vendor:0", "Purchase Receipt")
    adjust(c, h, p, 10, 20)
    original = c.get("/api/inventory/movements/" + str(receipt)).json["record"]
    r = command(
        c,
        h,
        "return",
        moveId=receipt,
        version=original["version"],
        quantity=4,
        reason="Vendor return",
        requestKey="return-retry-request",
    )
    assert Decimal(r["value"]) == -60
    command(
        c,
        h,
        "return",
        moveId=receipt,
        version=original["version"],
        quantity=4,
        reason="Vendor return",
        requestKey="return-retry-request",
    )
    command(
        c,
        h,
        "return",
        moveId=receipt,
        version=original["version"],
        quantity=1,
        reason="Stale return",
        expected=409,
    )
    original = detail(c, original)
    assert Decimal(original["returnRemaining"]) == 6
    command(
        c,
        h,
        "return",
        moveId=receipt,
        version=original["version"],
        quantity=7,
        reason="Too many",
        expected=400,
    )
    assert Decimal(product(c, p)["quantity"]) == 16


def test_readonly_company_scope_export_and_no_aggregate_reads(app, monkeypatch):
    c, h = session(app)
    p = make_product(c, h)
    adjust(c, h, p, 2)
    viewer, vh = session(app, "viewer")
    assert viewer.get("/api/inventory/products").json["total"] == 1
    command(
        viewer,
        vh,
        "adjust",
        productId=p,
        version=product(viewer, p)["version"],
        quantity=1,
        reason="No approval",
        expected=403,
    )
    assert viewer.get("/api/inventory/movements/export").status_code == 200
    hr, hh = session(app, "hr")
    assert hr.get("/api/inventory/products").status_code == 403
    original = Document.data

    def blocked(self):
        if self.name in ("app", "hr"):
            raise AssertionError(
                "Native inventory must not reconstruct aggregate state"
            )
        return original.fget(self)

    monkeypatch.setattr(Document, "data", property(blocked, original.fset))
    for path in ("summary", "products", "movements"):
        assert c.get("/api/inventory/" + path).status_code == 200
    adjust(c, h, p, 1)
    assert c.get("/api/inventory/products?pageSize=101").status_code == 400
    assert c.get("/api/inventory/movements/999999999999999999999999").status_code == 404


def test_paging_filters_export_and_upgrade_preserve_ledger(app):
    c, h = session(app)
    p = make_product(c, h, "=CSV formula")
    for n in range(3):
        adjust(c, h, p, 1)
    r = c.get("/api/inventory/movements?pageSize=1&page=2").json
    assert r["total"] == 3 and len(r["items"]) == 1
    assert c.get("/api/inventory/movements?search=NoMatch").json["total"] == 0
    assert (
        c.get("/api/inventory/movements?from=2026-11-01&to=2026-10-01").status_code
        == 400
    )
    export = c.get("/api/inventory/movements/export?pageSize=1")
    assert (
        export.status_code == 200
        and "'=CSV formula" in export.text
        and export.text.count("\n") == 2
    )
    with app.app_context():
        before = db.session.scalar(select(func.count()).select_from(JournalEntry))
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    assert Decimal(product(c, p)["quantity"]) == 3
    with app.app_context():
        assert (
            db.session.scalar(select(func.count()).select_from(JournalEntry)) == before
        )
