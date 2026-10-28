"""Real competing database connections: timeout rolls back, same key can retry."""

from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import event, select, update, func
from backend.test_app import app, session
from backend.app import db
from backend.erp import ERPControl, lock
from backend.hr_store import Employee


def test_busy_lock_returns_retry_and_same_command_can_succeed(app):
    client, headers = session(app)
    app.config["ERP_LOCK_TIMEOUT_MS"] = 50
    with app.app_context():
        engine = db.engine
        sqlite = engine.dialect.name == "sqlite"

    def short_wait(connection, record, proxy):
        connection.execute("PRAGMA busy_timeout=50")

    if sqlite:
        event.listen(engine, "checkout", short_wait)
    payload = dict(
        requestKey="contention-employee-001",
        employeeId="LOCK-EMP",
        name="Contention employee",
        department="Production",
        designation="Operator",
        joiningDate="2020-01-01",
        salary=10000,
    )
    try:
        with app.app_context():
            # Separate connection holds the control row while a real API request waits.
            db.session.execute(
                update(ERPControl)
                .where(ERPControl.id == 1)
                .values(revision=ERPControl.revision + 1)
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(
                    lambda: client.post(
                        "/api/hr/records/employees", headers=headers, json=payload
                    )
                ).result(timeout=10)
            assert response.status_code == 503, response.json
            assert response.headers["Retry-After"] == "1"
            assert "SQL" not in response.json["error"]
            db.session.rollback()
            assert db.session.scalar(select(func.count()).select_from(Employee)) == 0
        response = client.post(
            "/api/hr/records/employees", headers=headers, json=payload
        )
        assert response.status_code == 200, response.json
        replay = client.post("/api/hr/records/employees", headers=headers, json=payload)
        assert replay.status_code == 200
        assert replay.json["record"]["id"] == response.json["record"]["id"]
        with app.app_context():
            assert db.session.scalar(select(func.count()).select_from(Employee)) == 1
            if not sqlite:
                prior = db.session.scalar(select(func.current_setting("lock_timeout")))
                lock()
                assert (
                    db.session.scalar(select(func.current_setting("lock_timeout")))
                    == prior
                )
                db.session.rollback()
    finally:
        if sqlite:
            event.remove(engine, "checkout", short_wait)
