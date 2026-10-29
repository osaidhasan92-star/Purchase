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
from backend import hr_store as hr
from backend.test_hr_api import action as hr_action


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


def employee(c, h, key):
    r = c.post(
        "/api/hr/records/employees",
        headers=h,
        json=dict(
            requestKey="employee-" + key,
            employeeId="EMP-" + key,
            name="Synthetic employee",
            department="Production",
            designation="Operator",
            joiningDate="2020-01-01",
            salary=10000,
        ),
    )
    assert r.status_code == 200, r.json
    return r.json["record"]


def edit_values(resource, value):
    if resource == "attendance":
        return {"attendanceStatus": "Absent" if str(value).endswith("0") else "Late"}
    return {"reason" if resource == "manpower" else "contact": value}


def make_record(c, h, key, resource, parent=None):
    if resource == "manpower":
        return manpower(c, h, key)
    if resource == "attendance":
        parent = parent or employee(c, h, key)
        r = c.post(
            "/api/hr/records/attendance",
            headers=h,
            json=dict(
                requestKey=key,
                employeeKey=parent["id"],
                date="2026-10-29",
                attendanceStatus="Present",
            ),
        )
        assert r.status_code == 200, r.json
        return r.json["record"]
    payload = dict(
        requestKey=key,
        name="Synthetic candidate",
        position="Operator",
        contact="candidate@example.test",
    )
    if parent:
        payload["manpowerId"] = parent["id"]
    r = c.post("/api/hr/records/candidates", headers=h, json=payload)
    assert r.status_code == 200, r.json
    return r.json["record"]


def require_postgres(app):
    with app.app_context():
        if db.engine.dialect.name != "postgresql":
            pytest.skip(
                "PostgreSQL resource locks; SQLite retains global serialization"
            )


def _process_edit(url, identity, version, key, barrier, output, resource="manpower"):
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
            "/api/hr/records/" + resource + "/" + identity,
            headers=h,
            json={
                "requestKey": key,
                "version": version,
                **edit_values(resource, key),
            },
        )
        output.put(dict(status=r.status_code))
    except Exception as error:
        output.put(dict(failure=type(error).__name__))
    finally:
        with application.app_context():
            db.session.remove()
            db.engine.dispose()


@pytest.mark.parametrize("resource", ["manpower", "candidates", "attendance"])
def test_postgres_independent_records_overlap_across_processes(app, resource):
    require_postgres(app)
    c, h = session(app)
    parent = None
    if resource == "candidates":
        parent = manpower(c, h, "parallel-parent-setup")
        parent = hr_action(c, h, "manpower", parent, "approve")
    rows = [
        make_record(c, h, "parallel-setup-" + str(i), resource, parent)
        for i in range(2)
    ]
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
                resource,
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


@pytest.mark.parametrize("resource", ["manpower", "candidates", "attendance"])
def test_postgres_same_key_replays_and_same_record_rejects_stale_edit(app, resource):
    require_postgres(app)
    clients = [session(app), session(app)]
    parent = (
        employee(*clients[0], "same-key-parent") if resource == "attendance" else None
    )
    barrier = Barrier(2)

    def create(i):
        c, h = clients[i]
        barrier.wait(timeout=10)
        return make_record(c, h, "same-key-resource", resource, parent)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(create, range(2)))
    assert rows[0]["id"] == rows[1]["id"]
    with app.app_context():
        assert (
            db.session.scalar(select(func.count()).select_from(hr.MODELS[resource]))
            == 1
        )
    barrier = Barrier(2)

    def edit(i):
        c, h = clients[i]
        barrier.wait(timeout=10)
        return c.patch(
            "/api/hr/records/" + resource + "/" + rows[0]["id"],
            headers=h,
            json={
                "requestKey": "race-edit-" + str(i),
                "version": rows[0]["version"],
                **edit_values(resource, str(i)),
            },
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


@pytest.mark.parametrize("resource", ["manpower", "candidates", "attendance"])
def test_resource_locking_rollback_switch_keeps_original_global_path(app, resource):
    app.config["HR_RESOURCE_LOCKING"] = False
    c, h = session(app)
    parent = employee(c, h, "fallback-parent") if resource == "attendance" else None
    with app.app_context():
        before = db.session.get(ERPControl, 1).revision
    row = make_record(c, h, "fallback-resource-001", resource, parent)
    assert (
        row["status"]
        == {"manpower": "Pending", "candidates": "Applied", "attendance": "Recorded"}[
            resource
        ]
    )
    with app.app_context():
        assert db.session.get(ERPControl, 1).revision > before


@pytest.mark.parametrize("resource", ["manpower", "candidates", "attendance"])
def test_resource_write_failure_rolls_back_record_revision_and_receipt(
    app, monkeypatch, resource
):
    from backend.hr_context import Context
    from backend.hr_api import Command
    from backend.validation import InvalidBusinessState

    c, h = session(app)
    row = make_record(c, h, "rollback-setup-001", resource)
    with app.app_context():
        revision = db.session.get(Document, "hr").revision
    original = Context.persist

    def fail(self):
        original(self)
        raise InvalidBusinessState("Injected rollback check")

    changes = edit_values(resource, "Changed")
    field = next(iter(changes))
    payload = {"requestKey": "rollback-edit-001", "version": row["version"], **changes}
    monkeypatch.setattr(Context, "persist", fail)
    response = c.patch(
        "/api/hr/records/" + resource + "/" + row["id"], headers=h, json=payload
    )
    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(Document, "hr").revision == revision
        assert db.session.get(Command, ("admin", payload["requestKey"])) is None
    assert (
        c.get("/api/hr/records/" + resource + "/" + row["id"]).json["record"][field]
        == row[field]
    )
    monkeypatch.setattr(Context, "persist", original)
    assert (
        c.patch(
            "/api/hr/records/" + resource + "/" + row["id"], headers=h, json=payload
        ).status_code
        == 200
    )
    assert (
        c.patch(
            "/api/hr/records/" + resource + "/missing-record", headers=h, json=payload
        ).status_code
        == 404
    )


def test_postgres_candidate_parent_lock_times_out_without_partial_create(app):
    require_postgres(app)
    c, h = session(app)
    parent = hr_action(c, h, "manpower", manpower(c, h, "parent-lock-setup"), "approve")
    app.config["ERP_LOCK_TIMEOUT_MS"] = 50
    payload = dict(
        requestKey="parent-lock-candidate",
        name="Parent lock candidate",
        position="Operator",
        contact="candidate@example.test",
        manpowerId=parent["id"],
    )
    with app.app_context():
        db.session.execute(
            select(Manpower).where(Manpower.id == parent["id"]).with_for_update()
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(
                lambda: c.post("/api/hr/records/candidates", headers=h, json=payload)
            ).result(timeout=10)
        assert response.status_code == 503, response.json
        db.session.rollback()
        assert db.session.scalar(select(func.count()).select_from(hr.Candidate)) == 0
    response = c.post("/api/hr/records/candidates", headers=h, json=payload)
    assert response.status_code == 200, response.json
    replay = c.post("/api/hr/records/candidates", headers=h, json=payload)
    assert replay.json["record"]["id"] == response.json["record"]["id"]


def test_candidate_rejection_and_onboarding_race_remain_consistent(app):
    c, h = session(app)
    parent = hr_action(
        c, h, "manpower", manpower(c, h, "onboard-parent-setup"), "approve"
    )
    row = make_record(c, h, "onboard-candidate-setup", "candidates", parent)
    for action in ("shortlist", "interview", "select", "offer"):
        row = hr_action(c, h, "candidates", row, action)
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def race(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        if i == 0:
            return client.post(
                "/api/hr/records/candidates/" + row["id"] + "/actions/reject",
                headers=headers,
                json=dict(requestKey="race-reject-candidate", version=row["version"]),
            ).status_code
        return client.post(
            "/api/hr/records/employees",
            headers=headers,
            json=dict(
                requestKey="race-onboard-candidate",
                candidateId=row["id"],
                employeeId="RACE-EMP",
                name="Race employee",
                department="Production",
                designation="Operator",
                joiningDate="2020-01-01",
                salary=10000,
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        reject, onboard = list(pool.map(race, range(2)))
    assert (reject, onboard) in ((200, 400), (409, 200)), (reject, onboard)
    result = c.get("/api/hr/records/candidates/" + row["id"]).json["record"]
    with app.app_context():
        employees = db.session.scalar(select(func.count()).select_from(hr.Employee))
        assert employees == int(onboard == 200)
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 0
    assert result["stage"] == ("Hired" if onboard == 200 else "Rejected")


def test_attendance_duplicate_employee_day_and_date_edit_conflict(app):
    c, h = session(app)
    parent = employee(c, h, "duplicate-day-parent")
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def create(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return client.post(
            "/api/hr/records/attendance",
            headers=headers,
            json=dict(
                requestKey="duplicate-day-" + str(i),
                employeeKey=parent["id"],
                date="2026-10-29",
                attendanceStatus="Present",
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, range(2))) == [200, 409]
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(hr.Attendance)) == 1
    other = c.post(
        "/api/hr/records/attendance",
        headers=h,
        json=dict(
            requestKey="duplicate-day-other",
            employeeKey=parent["id"],
            date="2026-10-30",
            attendanceStatus="Present",
        ),
    )
    assert other.status_code == 200, other.json
    row = other.json["record"]
    response = c.patch(
        "/api/hr/records/attendance/" + row["id"],
        headers=h,
        json=dict(
            requestKey="duplicate-day-edit", version=row["version"], date="2026-10-29"
        ),
    )
    assert response.status_code == 409, response.json
    assert (
        c.get("/api/hr/records/attendance/" + row["id"]).json["record"]["date"]
        == "2026-10-30"
    )


def test_postgres_attendance_employee_lock_timeout_without_partial_create(app):
    require_postgres(app)
    c, h = session(app)
    parent = employee(c, h, "employee-lock-parent")
    app.config["ERP_LOCK_TIMEOUT_MS"] = 50
    payload = dict(
        requestKey="employee-lock-attendance",
        employeeKey=parent["id"],
        date="2026-10-29",
        attendanceStatus="Present",
    )
    with app.app_context():
        db.session.execute(
            select(hr.Employee).where(hr.Employee.id == parent["id"]).with_for_update()
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(
                lambda: c.post("/api/hr/records/attendance", headers=h, json=payload)
            ).result(timeout=10)
        assert response.status_code == 503, response.json
        db.session.rollback()
        assert db.session.scalar(select(func.count()).select_from(hr.Attendance)) == 0
    response = c.post("/api/hr/records/attendance", headers=h, json=payload)
    assert response.status_code == 200, response.json
    replay = c.post("/api/hr/records/attendance", headers=h, json=payload)
    assert replay.json["record"]["id"] == response.json["record"]["id"]


def test_attendance_legacy_label_resolution_and_duplicate_guard(app):
    from backend.hr_context import resource_references

    c, h = session(app)
    parent = employee(c, h, "legacy-label-parent")
    label = parent["employeeId"] + " - " + parent["name"]
    value = dict(
        id="legacy-attendance",
        employee=label,
        date="2026-10-29",
        attendanceStatus="Present",
        status="Recorded",
        createdBy="admin",
    )
    with app.app_context():
        row = hr.Attendance(id=value["id"])
        valid = {k: set() for k in hr.MODELS}
        valid["user"] = {"admin"}
        hr.write_one("attendance", value, row, 0, valid, [])
        db.session.add(row)
        db.session.commit()
        assert row.employee_id is None
        references = resource_references("attendance", row, {}, False)
        assert len(references) == 1 and references[0].identity == parent["id"]
        assert references[0].shared is False
    response = c.post(
        "/api/hr/records/attendance",
        headers=h,
        json=dict(
            requestKey="legacy-label-duplicate",
            employeeKey=parent["id"],
            date="2026-10-29",
            attendanceStatus="Present",
        ),
    )
    assert response.status_code == 409, response.json
    old = c.get("/api/hr/records/attendance/legacy-attendance").json["record"]
    response = c.patch(
        "/api/hr/records/attendance/legacy-attendance",
        headers=h,
        json=dict(
            requestKey="legacy-label-edit",
            version=old["version"],
            attendanceStatus="Late",
        ),
    )
    assert response.status_code == 200, response.json
    assert response.json["record"]["employeeKey"] == parent["id"]
    with app.app_context():
        assert (
            db.session.get(hr.Attendance, "legacy-attendance").employee_id
            == parent["id"]
        )
    # Preserve an ambiguous historical label instead of assigning an arbitrary FK.
    with app.app_context():
        duplicate = {k: v for k, v in parent.items() if k != "version"}
        duplicate["id"] = "duplicate-legacy-employee"
        e = hr.Employee(id=duplicate["id"])
        hr.write_one("employees", duplicate, e, 1, valid, [])
        db.session.add(e)
        ambiguous = {**value, "id": "ambiguous-attendance", "date": "2026-10-30"}
        a = hr.Attendance(id=ambiguous["id"])
        hr.write_one("attendance", ambiguous, a, 1, valid, [])
        db.session.add(a)
        db.session.commit()
        assert resource_references("attendance", a, {}, False) == []
    old = c.get("/api/hr/records/attendance/ambiguous-attendance").json["record"]
    response = c.patch(
        "/api/hr/records/attendance/ambiguous-attendance",
        headers=h,
        json=dict(
            requestKey="ambiguous-label-edit",
            version=old["version"],
            attendanceStatus="Late",
        ),
    )
    assert response.status_code == 409, response.json
    with app.app_context():
        assert db.session.get(hr.Attendance, "ambiguous-attendance").employee_id is None
