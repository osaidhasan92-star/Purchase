"""Query locality, conflict indexes, concurrency and full SQLite recovery drills."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3
import pytest
from sqlalchemy import select, func, event
from sqlalchemy.orm import Session
from backend.test_app import app, session
from backend.app import db, Document
from backend import trade_store as trade, hr_store as hr
from backend.test_trade_api import masters, purchase, receive_bill_pay, create, details
from backend.test_trade_api import (
    test_native_sales_approval_partial_deliveries_invoices_and_collections as run_sales,
)
from backend.test_hr_api import employee, payroll, action as hr_action
from backend.test_hr_api import (
    test_payroll_full_posting_idempotency_and_immutability as run_payroll,
)
from backend.workflow_keys import ConflictKey, tokens, replace
from backend.erp import JournalEntry, JournalLine


def block_aggregate(monkeypatch):
    from flask import has_request_context, request

    original = Document.data.fget

    def bounded(doc):
        if has_request_context() and request.path.startswith(
            ("/api/trade/", "/api/hr/records/", "/api/crm/")
        ):
            assert doc.name not in (
                "app",
                "hr",
            ), "Native workflow projected a company aggregate"
        return original(doc)

    monkeypatch.setattr(Document, "data", property(bounded, Document.data.fset))


def test_purchase_graph_posting_without_aggregate(app, monkeypatch):
    c, h = session(app)
    p, v, _ = masters(c, h)
    block_aggregate(monkeypatch)
    o = purchase(c, h, p, v)
    o, b = receive_bill_pay(c, h, o, 10, "LOCAL-BILL-1", 40)
    assert b["balance"] == 60 and o["status"] == "Partially Received"
    o, b = receive_bill_pay(c, h, o, 10, "LOCAL-BILL-2")
    assert o["invoiceStatus"] == "Invoiced" and o["paymentStatus"] == "Partially Paid"
    create(
        c,
        h,
        "payments",
        invoiceId=details(
            c, "invoices", c.get("/api/trade/invoices").json["items"][-1]["id"]
        )["id"],
        parentVersion=details(
            c, "invoices", c.get("/api/trade/invoices").json["items"][-1]["id"]
        )["version"],
        amount=60,
    )
    assert details(c, "orders", o["id"])["status"] == "Completed"


def test_sales_graph_without_aggregate(app, monkeypatch):
    block_aggregate(monkeypatch)
    run_sales(app)


def test_hr_posting_without_aggregate(app, monkeypatch):
    block_aggregate(monkeypatch)
    run_payroll(app)


def test_global_conflicts_across_unrelated_workflows(app):
    c, h = session(app)
    p, v, _ = masters(c, h)
    a = purchase(c, h, p, v)
    a, b = receive_bill_pay(c, h, a, 10, "GLOBAL-BILL-1", 40)
    create(
        c,
        h,
        "payments",
        invoiceId=b["id"],
        parentVersion=b["version"],
        amount=10,
        referenceNo="Straße",
    )
    z = purchase(c, h, p, v)
    z, other = receive_bill_pay(c, h, z, 10, "GLOBAL-BILL-2", 40)
    r = c.post(
        "/api/trade/payments",
        headers=h,
        json=dict(
            requestKey="unicode-reference-duplicate",
            invoiceId=other["id"],
            parentVersion=other["version"],
            amount=10,
            referenceNo="STRASSE",
        ),
    )
    assert r.status_code == 409, r.json
    assert details(c, "invoices", other["id"])["balance"] == 60
    from backend.erp import ERPCounter, day

    with app.app_context():
        next_id = db.session.get(ERPCounter, "PR").value + 1
        legacy_no = f"pr-{day()[:4]}-{next_id:06d}"
        value = dict(
            id="legacy-lower-number",
            requestNo=legacy_no,
            status="Draft",
            lineItems=[],
            items=0,
            total=0,
        )
        row = trade.MODELS["requests"](id=value["id"], position=100)
        trade.assign_header("requests", value, row, trade.available_ids({}))
        db.session.add(row)
        replace("requests", value)
        db.session.commit()
    fresh = create(
        c,
        h,
        "requests",
        department="Operations",
        items=[dict(productId=p["id"], quantity=1, rate=10)],
    )
    assert fresh["requestNo"].endswith(f"{next_id+1:06d}")
    e = employee(c, h, **{})
    payload = dict(
        name="Other",
        department="Production",
        designation="Operator",
        joiningDate="2026-10-01",
        employeeId=e["employeeId"].lower(),
        requestKey="duplicate-employee-id",
    )
    assert (
        c.post("/api/hr/records/employees", headers=h, json=payload).status_code == 409
    )

    with app.app_context():
        valid = {k: set() for k in hr.MODELS}
        valid["employees"] = {e["id"]}
        valid["user"] = set()
        for key, value in [
            (
                "leaves",
                dict(
                    id="legacy-null-leave",
                    employeeKey=e["id"],
                    employee=e["employeeId"] + " - " + e["name"],
                    status=None,
                    **{"from": "2026-11-01", "to": "2026-11-02"},
                    leaveType="Annual",
                ),
            ),
            (
                "separations",
                dict(
                    id="legacy-null-exit",
                    employeeKey=e["id"],
                    employee=e["employeeId"] + " - " + e["name"],
                    status=None,
                    lastWorkingDate="2026-12-01",
                ),
            ),
        ]:
            row = hr.MODELS[key](id=value["id"])
            hr.write_one(key, value, row, 0, valid, [])
            db.session.add(row)
        db.session.commit()
    response = c.post(
        "/api/hr/records/leaves",
        headers=h,
        json={
            "requestKey": "null-status-overlap",
            "employeeKey": e["id"],
            "from": "2026-11-01",
            "to": "2026-11-02",
            "leaveType": "Annual",
            "reason": "Overlap",
        },
    )
    assert response.status_code == 409, response.json
    response = c.post(
        "/api/hr/records/separations",
        headers=h,
        json={
            "requestKey": "null-status-exit",
            "employeeKey": e["id"],
            "lastWorkingDate": "2026-12-02",
            "reason": "Duplicate exit",
        },
    )
    assert response.status_code == 409, response.json


def test_unrelated_volume_does_not_load_or_rewrite_registers(app):
    c, h = session(app)
    p, v, _ = masters(c, h)
    r = create(
        c,
        h,
        "requests",
        department="Operations",
        items=[dict(productId=p["id"], quantity=1, rate=10)],
    )
    e = employee(c, h)
    loaded = []

    def track(s, obj):
        identity = getattr(obj, "id", "")
        if str(identity).startswith("noise-"):
            loaded.append((type(obj).__name__, identity))

    event.listen(Session, "loaded_as_persistent", track)
    try:
        with app.app_context():
            values = []
            for i in range(1000):
                value = dict(
                    id="noise-" + str(i),
                    requestNo="NOISE-" + str(i),
                    department="Other",
                    status="Draft",
                    lineItems=[],
                    items=0,
                    total=0,
                )
                row = trade.MODELS["requests"](id=value["id"], position=i + 10)
                trade.assign_header("requests", value, row, trade.available_ids({}))
                values.append(
                    {col.name: getattr(row, col.name) for col in row.__table__.columns}
                )
            db.session.execute(trade.MODELS["requests"].__table__.insert(), values)
            employees = []
            valid = {k: set() for k in hr.MODELS}
            valid["user"] = set()
            for i in range(1000):
                value = dict(
                    id="noise-emp-" + str(i),
                    employeeId="NOISE-EMP-" + str(i),
                    name="Other employee",
                    status="Active",
                    department="Other",
                    designation="Other",
                    joiningDate="2020-01-01",
                )
                row = hr.Employee(id=value["id"])
                hr.write_one("employees", value, row, i + 10, valid, [])
                employees.append(
                    {col.name: getattr(row, col.name) for col in row.__table__.columns}
                )
            db.session.execute(hr.Employee.__table__.insert(), employees)
            db.session.commit()
        loaded.clear()
        response = c.patch(
            "/api/trade/requests/" + str(r["id"]),
            headers=h,
            json=dict(
                version=r["version"],
                requestKey="local-only-edit-request",
                notes="Changed target",
            ),
        )
        assert response.status_code == 200, response.json
        response = c.patch(
            "/api/hr/records/employees/" + str(e["id"]),
            headers=h,
            json=dict(
                version=e["version"],
                requestKey="local-only-edit-employee",
                salary=12345,
            ),
        )
        assert response.status_code == 200, response.json
        assert loaded == []
        with app.app_context():
            assert (
                db.session.scalar(
                    select(func.count())
                    .select_from(trade.MODELS["requests"])
                    .where(trade.MODELS["requests"].notes == "Changed target")
                )
                == 1
            )
            assert (
                db.session.scalar(
                    select(func.count())
                    .select_from(hr.Employee)
                    .where(hr.Employee.salary == 12345)
                )
                == 1
            )
            assert (
                db.session.scalar(
                    select(func.count()).select_from(trade.MODELS["requests"])
                )
                == 1001
            )
    finally:
        event.remove(Session, "loaded_as_persistent", track)


def test_concurrent_payroll_period_conflict_and_action(app):
    c, h = session(app)
    e = employee(c, h)
    barrier = Barrier(2)

    def attempt(i):
        client, headers = session(app)
        barrier.wait()
        r = client.post(
            "/api/hr/records/payroll",
            headers=headers,
            json=dict(
                requestKey="parallel-payroll-" + str(i),
                employeeKey=e["id"],
                month="2026-10",
                basic=1000,
                allowances=0,
                deductions=0,
            ),
        )
        return r.status_code, r.json

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert sorted(r[0] for r in results) == [200, 409], results
    p = next(r[1]["record"] for r in results if r[0] == 200)
    barrier = Barrier(2)

    def approve(i):
        client, headers = session(app)
        barrier.wait()
        r = client.post(
            "/api/hr/records/payroll/" + p["id"] + "/actions/approve",
            headers=headers,
            json=dict(requestKey="parallel-approve-" + str(i), version=p["version"]),
        )
        return r.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, [1, 2]))
    assert sorted(results) == [200, 409]
    with app.app_context():
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(JournalEntry)
                .where(JournalEntry.source == "payroll:" + p["id"])
            )
            == 1
        )


def test_indexes_upgrade_preserves_business_and_ledgers(app):
    c, h = session(app)
    e = employee(c, h)
    p = payroll(c, h, e)
    hr_action(c, h, "payroll", p, "approve")
    with app.app_context():
        before = hr.read("employees")
        journal_ids = list(db.session.scalars(select(JournalEntry.id)))
        db.session.query(ConflictKey).delete()
        db.session.delete(db.session.get(Document, "workflow_indexes"))
        db.session.commit()
    assert (
        c.post(
            "/api/hr/records/manpower",
            headers=h,
            json=dict(requestKey="missing-indexes-command"),
        ).status_code
        == 503
    )
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert r.exit_code == 0, r.output
    with app.app_context():
        assert hr.read("employees") == before
        assert list(db.session.scalars(select(JournalEntry.id))) == journal_ids
        assert (
            db.session.scalar(
                select(ConflictKey.record_id).where(ConflictKey.domain == "employees")
            )
            == e["id"]
        )


def test_sqlite_backup_restore_retains_posted_workflows(app, tmp_path):
    with app.app_context():
        if db.engine.dialect.name != "sqlite":
            pytest.skip("PostgreSQL uses a pg_dump/pg_restore CI drill")
    c, h = session(app)
    assert c.post("/api/erp/seed-demo", headers=h, json={}).status_code == 200
    e = employee(c, h)
    p = payroll(c, h, e)
    p = hr_action(c, h, "payroll", p, "approve")
    hr_action(c, h, "payroll", p, "pay")
    with app.app_context():
        from backend.backup_verify import snapshot

        expected = snapshot(db.engine)
        target = str(tmp_path / "restored.sqlite")
        raw = db.engine.raw_connection()
        try:
            dest = sqlite3.connect(target)
            raw.driver_connection.backup(dest)
            assert dest.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert dest.execute("PRAGMA foreign_key_check").fetchall() == []
            dest.close()
        finally:
            raw.close()
    from backend.app import create_app

    restored = create_app(
        {
            "TESTING": True,
            "COOKIE_SECURE": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + target,
        }
    )
    with restored.app_context():
        assert snapshot(db.engine) == expected
    recovered, rh = session(restored)
    assert (
        recovered.get("/api/hr/records/payroll/" + p["id"]).json["record"]["status"]
        == "Paid"
    )
    assert float(recovered.get("/api/finance/summary").json["balanceCheck"]) == 0


def test_workflow_health_and_derived_rebuild(app):
    c, h = session(app)
    e = employee(c, h)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["workflow-health"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        before = hr.read("employees")
        db.session.add(
            ConflictKey(
                domain="employees",
                kind="number",
                record_id="legacy-duplicate",
                token=tokens("employees", e)["number"],
            )
        )
        db.session.commit()
    result = runner.invoke(args=["workflow-health"])
    assert result.exit_code == 1 and '"duplicateWorkflowKeys": 1' in result.output
    assert runner.invoke(args=["rebuild-workflow-indexes"]).exit_code == 0
    assert runner.invoke(args=["workflow-health"]).exit_code == 0
    with app.app_context():
        assert hr.read("employees") == before
