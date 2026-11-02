"""Native module resource overlap, shared-resource conflicts and reservation migration."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import multiprocessing
import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from backend.test_app import app, session
from backend.app import db, Document
from backend.erp import ERPControl, JournalEntry, StockBalance, Reconciliation
from backend.test_inventory_api import make_product, adjust, product
from backend.test_trade_api import masters, create as trade_create
from backend.test_production_api import (
    command as production,
    order as make_order,
    action as production_action,
    detail as order_detail,
)
from backend.test_expense_api import create as expense_create, act as expense_action
from backend.test_resource_concurrency import require_postgres, make_record
from backend.unique_reservations import Reservation, initialize
from backend.workflow_keys import ConflictKey, tokens
from backend.workflow_health import report


def worker(url, path, method, payload, barrier, output, seam="tail"):
    from flask import g
    from backend.app import create_app
    from backend import concurrency, db_contention, expense_api

    application = create_app(
        dict(SQLALCHEMY_DATABASE_URI=url, TESTING=True, COOKIE_SECURE=False)
    )
    original_tail = concurrency.acquire_payroll_posting

    def rendezvous():
        if not getattr(g, "test_rendezvous", False):
            g.test_rendezvous = True
            barrier.wait(timeout=20)
        return original_tail()

    if seam == "tail":
        concurrency.acquire_payroll_posting = rendezvous
        db_contention.acquire_payroll_posting = rendezvous
    else:
        original = expense_api.transition

        def transition(*args):
            barrier.wait(timeout=20)
            return original(*args)

        expense_api.transition = transition
    try:
        c, h = session(application)
        r = c.open(path, method=method, headers=h, json=payload)
        output.put(dict(status=r.status_code, error=(r.json or {}).get("error")))
    except Exception as error:
        output.put(dict(failure=type(error).__name__))
    finally:
        with application.app_context():
            db.session.remove()
            db.engine.dispose()


def run_processes(app, operations, seam="tail"):
    ctx = multiprocessing.get_context("spawn")
    barrier, output = ctx.Barrier(2), ctx.Queue()
    processes = [
        ctx.Process(
            target=worker,
            args=(
                app.config["SQLALCHEMY_DATABASE_URI"],
                path,
                method,
                payload,
                barrier,
                output,
                seam,
            ),
        )
        for path, method, payload in operations
    ]
    try:
        for p in processes:
            p.start()
        results = [output.get(timeout=45) for _ in processes]
        for p in processes:
            p.join(timeout=10)
        assert all(p.exitcode == 0 for p in processes), results
        assert results == [dict(status=200, error=None)] * 2, results
    finally:
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)
        output.close()


@pytest.mark.parametrize(
    "module",
    [
        "inventory",
        "purchase",
        "sales",
        "manufacturing",
        "expenses",
        "finance",
        "mixed-payroll-stock",
    ],
)
def test_postgres_independent_native_modules_prepare_across_processes(app, module):
    require_postgres(app)
    c, h = session(app)
    operations = []
    _, _, customer = masters(c, h)
    for i in range(2):
        key = "module-process-" + str(i)
        p = make_product(c, h, "Concurrent raw " + str(i))
        if module in ("inventory", "mixed-payroll-stock", "manufacturing"):
            adjust(c, h, p, 20)
        if module == "inventory" or module == "mixed-payroll-stock" and i == 0:
            operations.append(
                (
                    "/api/inventory/commands/scrap",
                    "POST",
                    dict(
                        requestKey=key,
                        productId=p,
                        quantity=1,
                        date="2026-10-28",
                        reason="Concurrent scrap",
                        version=product(c, p)["version"],
                    ),
                )
            )
        elif module == "mixed-payroll-stock":
            row = make_record(c, h, key + "-setup", "payroll")
            operations.append(
                (
                    "/api/hr/records/payroll/" + row["id"] + "/actions/approve",
                    "POST",
                    dict(requestKey=key, version=row["version"]),
                )
            )
        elif module in ("purchase", "sales"):
            register = "requests" if module == "purchase" else "salesQuotations"
            data = (
                dict(
                    department="Operations",
                    items=[dict(productId=p, quantity=1, rate=10)],
                )
                if module == "purchase"
                else dict(
                    customerId=customer["id"],
                    items=[dict(productId=p, quantity=1, rate=10)],
                )
            )
            row = trade_create(c, h, register, **data)
            operations.append(
                (
                    "/api/trade/" + register + "/" + str(row["id"]),
                    "PATCH",
                    dict(
                        requestKey=key, version=row["version"], notes="Concurrent note"
                    ),
                )
            )
        elif module == "manufacturing":
            out = make_product(c, h, "Concurrent finished " + str(i))
            bom = production(
                c,
                h,
                "bom",
                name="Concurrent BoM",
                productId=out,
                quantity=1,
                conversionCost=0,
                components=[dict(productId=p, quantity=2)],
            )
            row = make_order(c, h, bom)
            row = production_action(c, h, row, "confirm")
            row = order_detail(c, row)
            operations.append(
                (
                    "/api/production/commands/complete",
                    "POST",
                    dict(requestKey=key, id=row["id"], version=row["version"]),
                )
            )
        elif module == "expenses":
            row = expense_create(c, h)
            operations.append(
                (
                    "/api/expenses/commands/submit",
                    "POST",
                    dict(requestKey=key, id=row["id"], version=row["version"]),
                )
            )
        else:
            operations.append(
                (
                    "/api/finance/commands/account",
                    "POST",
                    dict(
                        requestKey=key,
                        code="89" + str(i) + "0",
                        name="Concurrent account",
                        type="expense",
                        reconcile=False,
                    ),
                )
            )
    with app.app_context():
        control = db.session.get(ERPControl, 1).revision
    run_processes(app, operations, "expense" if module == "expenses" else "tail")
    with app.app_context():
        assert db.session.get(ERPControl, 1).revision == control
        assert report()["healthy"]
        for entry in db.session.scalars(select(JournalEntry)):
            assert sum(l.debit for l in entry.lines) == sum(
                l.credit for l in entry.lines
            )


def test_same_product_competing_scrap_preserves_stock_and_rejects_stale_version(app):
    c, h = session(app)
    p = make_product(c, h, "Scarce stock")
    adjust(c, h, p, 10)
    version = product(c, p)["version"]
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def scrap(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return client.post(
            "/api/inventory/commands/scrap",
            headers=headers,
            json=dict(
                requestKey="competing-scrap-" + str(i),
                productId=p,
                quantity=7,
                date="2026-10-28",
                reason="Concurrent issue",
                version=version,
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(scrap, range(2))) == [200, 409]
    assert float(product(c, p)["quantity"]) == 3
    with app.app_context():
        assert report()["healthy"]


def test_competing_manufacturing_orders_cannot_consume_same_stock_twice(app):
    c, h = session(app)
    p, out = make_product(c, h, "Shared raw"), make_product(c, h, "Shared finished")
    adjust(c, h, p, 10)
    bom = production(
        c,
        h,
        "bom",
        name="Shared BoM",
        productId=out,
        quantity=1,
        conversionCost=0,
        components=[dict(productId=p, quantity=2)],
    )
    rows = [
        production_action(c, h, make_order(c, h, bom, 4), "confirm") for _ in range(2)
    ]
    rows = [order_detail(c, row) for row in rows]
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def complete(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return client.post(
            "/api/production/commands/complete",
            headers=headers,
            json=dict(
                requestKey="competing-mo-" + str(i),
                id=rows[i]["id"],
                version=rows[i]["version"],
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(complete, range(2)))
    assert codes[0] == 200 and codes[1] in (400, 409), codes
    assert float(product(c, p)["quantity"]) == 2
    assert float(product(c, out)["quantity"]) == 4


def test_expense_payment_race_posts_one_reimbursement(app):
    c, h = session(app)
    row = expense_create(c, h)
    row = expense_action(c, h, row, "submit")
    row = expense_action(c, h, row, "approve")
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def pay(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return client.post(
            "/api/expenses/commands/pay",
            headers=headers,
            json=dict(
                requestKey="expense-race-" + str(i),
                id=row["id"],
                version=row["version"],
                account="1010",
                date="2026-10-28",
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(pay, range(2))) == [200, 409]
    with app.app_context():
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(JournalEntry)
                .where(JournalEntry.source == f"expense:{row['id']}:payment")
            )
            == 1
        )
        assert db.session.scalar(select(func.count()).select_from(Reconciliation)) == 1


def test_unique_reservation_backfill_blocks_legacy_duplicates_without_reposting(app):
    c, h = session(app)
    with app.app_context():
        token = tokens("employees", dict(id="one", employeeId="LEGACY-DUP"))["number"]
        for identity in ("one", "two"):
            db.session.add(
                ConflictKey(
                    domain="employees", kind="number", token=token, record_id=identity
                )
            )
        db.session.flush()
        before = db.session.scalar(select(func.count()).select_from(JournalEntry))
        initialize(rebuild=True)
        db.session.commit()
        assert (
            db.session.get(Reservation, ("employees", "number", token)).record_id
            is None
        )
        assert (
            db.session.scalar(select(func.count()).select_from(JournalEntry)) == before
        )
        with pytest.raises(IntegrityError):
            with db.session.begin_nested():
                db.session.add(
                    Reservation(
                        domain="employees",
                        kind="number",
                        token=token,
                        record_id="third",
                    )
                )
                db.session.flush()


def race_posts(app, path, payloads):
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def post(i):
        c, h = clients[i]
        barrier.wait(timeout=10)
        return c.post(path, headers=h, json=payloads[i]).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(post, range(2)))


def test_purchase_receipt_race_cannot_overreceive_source_order(app):
    from backend.test_trade_api import purchase, details

    c, h = session(app)
    p, v, _ = masters(c, h)
    row = purchase(c, h, p, v)
    codes = race_posts(
        app,
        "/api/trade/receipts",
        [
            dict(
                requestKey="receipt-race-" + str(i),
                poId=row["id"],
                parentVersion=row["version"],
                items=[
                    dict(lineIndex=0, receivedQty=15, acceptedQty=15, rejectedQty=0)
                ],
            )
            for i in range(2)
        ],
    )
    assert codes.count(200) == 1 and any(code in (400, 409) for code in codes), codes
    assert float(product(c, p["id"])["quantity"]) == 15
    with app.app_context():
        assert report()["healthy"]


def test_sales_delivery_reservations_and_validation_conserve_source_quantity(app):
    from backend.test_trade_api import action, details

    c, h = session(app)
    p, _, customer = masters(c, h)
    adjust(c, h, p["id"], 20)
    quote = trade_create(
        c,
        h,
        "salesQuotations",
        customerId=customer["id"],
        items=[dict(productId=p["id"], quantity=10, rate=10)],
    )
    for step in ("submit", "approve", "send", "accept"):
        quote = action(c, h, "salesQuotations", quote, step)
    row = trade_create(
        c, h, "salesOrders", quotationId=quote["id"], parentVersion=quote["version"]
    )
    codes = race_posts(
        app,
        "/api/trade/deliveries",
        [
            dict(
                requestKey="delivery-race-" + str(i),
                orderId=row["id"],
                parentVersion=row["version"],
                items=[dict(lineIndex=0, deliveredQty=6)],
            )
            for i in range(2)
        ],
    )
    assert codes.count(200) == 1 and any(code in (400, 409) for code in codes), codes
    row = details(c, "salesOrders", row["id"])
    trade_create(
        c,
        h,
        "deliveries",
        orderId=row["id"],
        parentVersion=row["version"],
        items=[dict(lineIndex=0, deliveredQty=4)],
    )
    deliveries = c.get("/api/trade/deliveries").json["items"]
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def deliver(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return client.post(
            "/api/trade/deliveries/" + str(deliveries[i]["id"]) + "/actions/deliver",
            headers=headers,
            json=dict(
                requestKey="validate-delivery-" + str(i),
                version=deliveries[i]["version"],
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(deliver, range(2))) == [200, 200]
    assert float(product(c, p["id"])["quantity"]) == 10


def test_finance_reconciliation_race_cannot_match_same_balance_twice(app):
    from backend.test_finance_api import journal, post

    c, h = session(app)
    debit = post(
        c, h, journal(c, h, debit="1100", credit="4100", partner="customer:race")
    )
    credit = post(
        c, h, journal(c, h, debit="1000", credit="1100", partner="customer:race")
    )
    d = next(line for line in debit["lines"] if line["account"] == "1100")
    cr = next(line for line in credit["lines"] if line["account"] == "1100")
    codes = race_posts(
        app,
        "/api/finance/commands/reconcile",
        [
            dict(
                requestKey="reconcile-race-" + str(i),
                debitLine=d["id"],
                creditLine=cr["id"],
                debitVersion=d["version"],
                creditVersion=cr["version"],
                amount=100,
            )
            for i in range(2)
        ],
    )
    assert sorted(codes) == [200, 409], codes
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Reconciliation)) == 1
        assert db.session.scalar(select(func.sum(Reconciliation.amount))) == 100


def test_finance_reversal_race_creates_exactly_one_reversal(app):
    from backend.test_finance_api import journal, post

    c, h = session(app)
    row = post(c, h, journal(c, h))
    codes = race_posts(
        app,
        "/api/finance/commands/reverse",
        [
            dict(
                requestKey="reverse-race-" + str(i),
                id=row["id"],
                version=row["version"],
                date="2026-10-28",
            )
            for i in range(2)
        ],
    )
    assert codes.count(200) == 1 and any(code in (400, 409) for code in codes), codes
    with app.app_context():
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(JournalEntry)
                .where(JournalEntry.reversal_of == row["id"])
            )
            == 1
        )


def test_inventory_and_manufacturing_share_one_product_lock(app):
    c, h = session(app)
    p, out = make_product(c, h, "Mixed raw"), make_product(c, h, "Mixed finished")
    adjust(c, h, p, 10)
    bom = production(
        c,
        h,
        "bom",
        name="Mixed BoM",
        productId=out,
        quantity=1,
        conversionCost=0,
        components=[dict(productId=p, quantity=2)],
    )
    row = order_detail(c, production_action(c, h, make_order(c, h, bom, 4), "confirm"))
    clients = [session(app), session(app)]
    version = product(c, p)["version"]
    barrier = Barrier(2)

    def consume(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        if i == 0:
            return client.post(
                "/api/inventory/commands/scrap",
                headers=headers,
                json=dict(
                    requestKey="mixed-scrap",
                    productId=p,
                    version=version,
                    quantity=7,
                    date="2026-10-28",
                    reason="Competing consumption",
                ),
            ).status_code
        return client.post(
            "/api/production/commands/complete",
            headers=headers,
            json=dict(
                requestKey="mixed-complete", id=row["id"], version=row["version"]
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(consume, range(2)))
    assert codes.count(200) == 1 and any(code in (400, 409) for code in codes), codes
    assert float(product(c, p)["quantity"]) in (2, 3)
    with app.app_context():
        assert report()["healthy"]


def test_postgres_legacy_import_is_excluded_by_active_resource_gate(app):
    require_postgres(app)
    c, h = session(app)
    app.config["ERP_LOCK_TIMEOUT_MS"] = 50
    payload = dict(
        format=1,
        app=dict(
            vendors=[dict(id="import-vendor", name="Imported vendor", status="Active")]
        ),
        hr={},
    )
    with app.app_context():
        db.session.execute(
            select(ERPControl.id).where(ERPControl.id == 1).with_for_update(read=True)
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            r = pool.submit(
                lambda: c.post("/api/admin/import", headers=h, json=payload)
            ).result(timeout=10)
        assert r.status_code == 503, r.json
        db.session.rollback()
    r = c.post("/api/admin/import", headers=h, json=payload)
    assert r.status_code == 200, r.json
    assert c.get("/api/vendors").json["items"][0]["id"] == "import-vendor"
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_legacy_user_manager_assignments_cannot_create_a_concurrent_cycle(app):
    clients = [session(app), session(app)]
    barrier = Barrier(2)
    identities = ["viewer", "hr"]

    def update(i):
        c, h = clients[i]
        barrier.wait(timeout=10)
        return c.put(
            "/api/users/" + identities[i],
            headers=h,
            json=dict(
                name=identities[i],
                email=identities[i] + "@example.test",
                role="Viewer" if i == 0 else "HR Manager",
                active=True,
                managerId=identities[1 - i],
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(update, range(2)))
    assert sorted(codes) == [200, 400], codes
    from backend.app import User

    with app.app_context():
        assert not (
            db.session.get(User, "viewer").manager_id == "hr"
            and db.session.get(User, "hr").manager_id == "viewer"
        )
