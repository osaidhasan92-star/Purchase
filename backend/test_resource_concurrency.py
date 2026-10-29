"""PostgreSQL cross-process overlap and compatibility of resource-level HR writes."""

from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from threading import Barrier
import pytest
from sqlalchemy import select, update, func
from backend.test_app import app, session
from backend.app import db, Document
from backend.erp import ERPControl, JournalEntry
from backend.hr_store import Manpower


def manpower(c, h, key):
    r = c.post(
        "/api/hr/records/manpower",
        headers=h,
        json=dict(
            requestKey=key,
            department="Production",
            position="Operator",
            count=1,
            requestType="New Position",
            reason="Capacity",
            requestedBy="Manager",
        ),
    )
    assert r.status_code == 200, r.json
    return r.json["record"]


def require_postgres(app):
    with app.app_context():
        if db.engine.dialect.name != "postgresql":
            pytest.skip(
                "PostgreSQL resource locks; SQLite retains global serialization"
            )


def _process_edit(url, identity, version, key, barrier, output):
    """Separate app, pool, connection and process; fail if both cannot reach validation."""
    from backend.app import create_app
    from backend.hr_context import Context

    application = create_app(
        dict(SQLALCHEMY_DATABASE_URI=url, TESTING=True, COOKIE_SECURE=False)
    )
    original = Context.validate

    def rendezvous(self):
        original(self)
        barrier.wait(timeout=15)

    Context.validate = rendezvous
    try:
        c, h = session(application)
        r = c.patch(
            "/api/hr/records/manpower/" + identity,
            headers=h,
            json=dict(requestKey=key, version=version, reason=key),
        )
        output.put(dict(status=r.status_code))
    except Exception as error:
        output.put(dict(failure=type(error).__name__))
    finally:
        with application.app_context():
            db.session.remove()
            db.engine.dispose()


def test_postgres_independent_records_overlap_across_processes(app):
    require_postgres(app)
    c, h = session(app)
    rows = [manpower(c, h, "parallel-setup-" + str(i)) for i in range(2)]
    with app.app_context():
        revision = db.session.get(Document, "hr").revision
        control = db.session.get(ERPControl, 1).revision
    ctx = multiprocessing.get_context("spawn")
    barrier, output = ctx.Barrier(2), ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_edit,
            args=(
                app.config["SQLALCHEMY_DATABASE_URI"],
                row["id"],
                row["version"],
                "parallel-process-" + str(i),
                barrier,
                output,
            ),
        )
        for i, row in enumerate(rows)
    ]
    try:
        for p in processes:
            p.start()
        results = [output.get(timeout=30) for _ in processes]
        for p in processes:
            p.join(timeout=10)
        assert all(p.exitcode == 0 for p in processes), results
        assert results == [dict(status=200), dict(status=200)], results
        with app.app_context():
            assert db.session.get(Document, "hr").revision == revision + 2
            assert db.session.get(ERPControl, 1).revision == control
            assert (
                db.session.scalar(select(func.count()).select_from(JournalEntry)) == 0
            )
    finally:
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)
        output.close()


def test_postgres_same_key_replays_and_same_record_rejects_stale_edit(app):
    require_postgres(app)
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def create(i):
        c, h = clients[i]
        barrier.wait(timeout=10)
        return manpower(c, h, "same-key-manpower")

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(create, range(2)))
    assert rows[0]["id"] == rows[1]["id"]
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Manpower)) == 1
    barrier = Barrier(2)

    def edit(i):
        c, h = clients[i]
        barrier.wait(timeout=10)
        return c.patch(
            "/api/hr/records/manpower/" + rows[0]["id"],
            headers=h,
            json=dict(
                requestKey="race-edit-" + str(i),
                version=rows[0]["version"],
                reason=str(i),
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, range(2))) == [200, 409]


def test_postgres_resource_gate_and_global_writer_exclude_each_other(app):
    require_postgres(app)
    c, h = session(app)
    app.config["ERP_LOCK_TIMEOUT_MS"] = 50
    with app.app_context():
        db.session.execute(
            update(ERPControl)
            .where(ERPControl.id == 1)
            .values(revision=ERPControl.revision + 1)
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(
                lambda: c.post(
                    "/api/hr/records/manpower",
                    headers=h,
                    json=dict(
                        requestKey="exclusive-gate-test",
                        department="Production",
                        position="Operator",
                        count=1,
                    ),
                )
            ).result(timeout=10)
        assert response.status_code == 503, response.json
        db.session.rollback()
        assert db.session.scalar(select(func.count()).select_from(Manpower)) == 0
        db.session.rollback()
        db.session.execute(
            select(ERPControl.id).where(ERPControl.id == 1).with_for_update(read=True)
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(
                lambda: c.post(
                    "/api/hr/records/employees",
                    headers=h,
                    json=dict(
                        requestKey="shared-gate-test",
                        employeeId="GATE-EMP",
                        name="Blocked employee",
                        department="Production",
                        designation="Operator",
                        joiningDate="2020-01-01",
                        salary=10000,
                    ),
                )
            ).result(timeout=10)
        assert response.status_code == 503, response.json
        db.session.rollback()
    manpower(c, h, "exclusive-gate-test")


def test_resource_locking_rollback_switch_keeps_original_global_path(app):
    app.config["HR_RESOURCE_LOCKING"] = False
    c, h = session(app)
    with app.app_context():
        before = db.session.get(ERPControl, 1).revision
    row = manpower(c, h, "fallback-manpower-001")
    assert row["status"] == "Pending"
    with app.app_context():
        assert db.session.get(ERPControl, 1).revision > before


def test_resource_write_failure_rolls_back_record_revision_and_receipt(
    app, monkeypatch
):
    from backend.hr_context import Context
    from backend.hr_api import Command
    from backend.validation import InvalidBusinessState

    c, h = session(app)
    row = manpower(c, h, "rollback-setup-001")
    with app.app_context():
        revision = db.session.get(Document, "hr").revision
    original = Context.persist

    def fail(self):
        original(self)
        raise InvalidBusinessState("Injected rollback check")

    payload = dict(
        requestKey="rollback-edit-001", version=row["version"], reason="Changed"
    )
    monkeypatch.setattr(Context, "persist", fail)
    response = c.patch("/api/hr/records/manpower/" + row["id"], headers=h, json=payload)
    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(Document, "hr").revision == revision
        assert db.session.get(Command, ("admin", payload["requestKey"])) is None
    assert (
        c.get("/api/hr/records/manpower/" + row["id"]).json["record"]["reason"]
        == "Capacity"
    )
    monkeypatch.setattr(Context, "persist", original)
    assert (
        c.patch(
            "/api/hr/records/manpower/" + row["id"], headers=h, json=payload
        ).status_code
        == 200
    )
    assert (
        c.patch(
            "/api/hr/records/manpower/missing-record", headers=h, json=payload
        ).status_code
        == 404
    )
