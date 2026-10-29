"""Leave-range reservations, concurrent transitions and manager scope."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
import pytest
from sqlalchemy import select, func
from backend.test_app import app, session
from backend.app import db, Document, Audit
from backend import hr_store as hr
from backend.erp import JournalEntry
from backend.test_resource_concurrency import employee


def payload(parent, key, start="2026-11-01", end="2026-11-03"):
    return {
        "requestKey": key,
        "employeeKey": parent["id"],
        "from": start,
        "to": end,
        "leaveType": "Annual",
        "reason": "Personal",
    }


def create(c, h, parent, key, start="2026-11-01", end="2026-11-03"):
    r = c.post(
        "/api/hr/records/leaves", headers=h, json=payload(parent, key, start, end)
    )
    assert r.status_code == 200, r.json
    return r.json["record"]


def action(c, h, row, command, key):
    return c.post(
        "/api/hr/records/leaves/" + row["id"] + "/actions/" + command,
        headers=h,
        json=dict(requestKey=key, version=row["version"]),
    )


def test_leave_parallel_submissions_reserve_inclusive_ranges(app):
    c, h = session(app)
    parent = employee(c, h, "leave-range-parent")
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def submit(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return client.post(
            "/api/hr/records/leaves",
            headers=headers,
            json=payload(
                parent,
                "leave-range-race-" + str(i),
                "2026-11-01" if i == 0 else "2026-11-03",
                "2026-11-03" if i == 0 else "2026-11-05",
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [200, 409]
    with app.app_context():
        row = db.session.scalar(select(hr.Leave))
        old = hr.record("leaves", row)
        assert db.session.scalar(select(func.count()).select_from(hr.Leave)) == 1
    # Endpoints count as an overlap, but the following day remains available.
    end = old["to"]
    from datetime import date, timedelta

    next_day = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    other = create(c, h, parent, "leave-adjacent", next_day, next_day)
    assert other["days"] == 1
    r = c.patch(
        "/api/hr/records/leaves/" + other["id"],
        headers=h,
        json={
            "requestKey": "leave-range-edit",
            "version": other["version"],
            "from": end,
            "to": next_day,
        },
    )
    assert r.status_code == 409, r.json
    assert (
        c.get("/api/hr/records/leaves/" + other["id"]).json["record"]["from"]
        == next_day
    )


@pytest.mark.parametrize("command", ["cancel", "reject"])
def test_leave_terminal_transition_racing_new_submission_releases_range(app, command):
    c, h = session(app)
    parent = employee(c, h, "leave-release-parent")
    row = create(c, h, parent, "leave-release-original")
    clients = [session(app), session(app)]
    barrier = Barrier(2)
    body = payload(parent, "leave-release-new")

    def race(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return (
            action(client, headers, row, command, "leave-release-action").status_code
            if i == 0
            else client.post(
                "/api/hr/records/leaves", headers=headers, json=body
            ).status_code
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        terminal, submitted = list(pool.map(race, range(2)))
    assert terminal == 200 and submitted in (200, 409), (terminal, submitted)
    # A failed reservation has no receipt/partial row and the same key can retry.
    response = c.post("/api/hr/records/leaves", headers=h, json=body)
    assert response.status_code == 200, response.json
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(hr.Leave)) == 2
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(hr.Leave)
                .where(hr.Leave.status == "Pending")
            )
            == 1
        )
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_leave_concurrent_approval_and_cancellation_reject_stale_transition(app):
    c, h = session(app)
    parent = employee(c, h, "leave-transition-parent")
    row = create(c, h, parent, "leave-transition-setup")
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def transition(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return action(
            client,
            headers,
            row,
            "approve" if i == 0 else "cancel",
            "leave-transition-" + str(i),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(transition, range(2)))
    assert sorted(codes) == [200, 409]
    winner = codes.index(200)
    replay = action(
        *clients[winner],
        row,
        "approve" if winner == 0 else "cancel",
        "leave-transition-" + str(winner)
    )
    assert replay.status_code == 200
    assert replay.json["record"]["status"] == (
        "Approved" if winner == 0 else "Cancelled"
    )
    with app.app_context():
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(Audit)
                .where(Audit.action.in_(["HR approve", "HR cancel"]))
            )
            == 1
        )


def seed_legacy(app, parent, key, start="2026-11-01", end="2026-11-03"):
    value = {
        "id": key,
        "employeeKey": parent["id"],
        "employee": parent["employeeId"] + " - " + parent["name"],
        "from": start,
        "to": end,
        "leaveType": "Annual",
        "reason": "Legacy",
        "days": 3,
        "status": "Pending",
        "createdBy": "admin",
    }
    with app.app_context():
        row = hr.Leave(id=key)
        valid = {k: set() for k in hr.MODELS}
        valid["user"], valid["employees"] = {"admin"}, {parent["id"]}
        hr.write_one("leaves", value, row, 0, valid, [])
        db.session.add(row)
        db.session.commit()


def test_legacy_overlapping_leaves_cannot_both_be_approved(app):
    c, h = session(app)
    parent = employee(c, h, "leave-history-parent")
    for key in ("legacy-leave-a", "legacy-leave-b"):
        seed_legacy(app, parent, key)
    rows = [
        c.get("/api/hr/records/leaves/" + key).json["record"]
        for key in ("legacy-leave-a", "legacy-leave-b")
    ]
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def approve(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return action(
            client, headers, rows[i], "approve", "legacy-leave-approve-" + str(i)
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(approve, range(2))) == [409, 409]
    assert action(c, h, rows[1], "reject", "legacy-leave-reject").status_code == 200
    retried = action(c, h, rows[0], "approve", "legacy-leave-approve-0")
    assert retried.status_code == 200, retried.json
    with app.app_context():
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(hr.Leave)
                .where(hr.Leave.status == "Approved")
            )
            == 1
        )


@pytest.mark.parametrize("start", ["not-a-date", "2026-11-04"])
def test_malformed_legacy_leave_cannot_be_approved_but_can_be_rejected(app, start):
    c, h = session(app)
    parent = employee(c, h, "leave-invalid-parent")
    seed_legacy(app, parent, "legacy-invalid-leave", start)
    row = c.get("/api/hr/records/leaves/legacy-invalid-leave").json["record"]
    r = action(c, h, row, "approve", "legacy-invalid-approve")
    assert r.status_code == 400, r.json
    assert (
        c.get("/api/hr/records/leaves/legacy-invalid-leave").json["record"]["status"]
        == "Pending"
    )
    assert action(c, h, row, "reject", "legacy-invalid-reject").status_code == 200


def test_leave_self_manager_scope_and_pending_only_cancellation(app):
    c, h = session(app)
    parent = employee(c, h, "leave-scope-parent")
    with app.app_context():
        db.session.get(hr.Employee, parent["id"]).linked_user_id = "seller"
        doc = db.session.get(Document, "app")
        state = deepcopy(doc.stored_data)
        for role in ("Salesperson", "Sales Manager", "Viewer"):
            state["roles"][role]["permissions"]["hr_employees"] = dict(
                view=False, create=False, edit=False, approve=False, export=False
            )
            state["roles"][role]["permissions"]["hr_leave"] = dict(
                view=True,
                create=True,
                edit=True,
                approve=role != "Salesperson",
                export=False,
            )
        doc.stored_data = state
        db.session.commit()
    own, oh = session(app, "seller")
    manager, mh = session(app, "manager")
    other, vh = session(app, "viewer")
    row = create(own, oh, parent, "leave-scope-own")
    assert (
        action(own, oh, row, "approve", "leave-scope-self-approve").status_code == 403
    )
    assert other.get("/api/hr/records/leaves/" + row["id"]).status_code == 404
    assert (
        action(other, vh, row, "approve", "leave-scope-unrelated-approve").status_code
        == 404
    )
    r = action(manager, mh, row, "approve", "leave-scope-manager-approve")
    assert r.status_code == 200, r.json
    assert (
        action(
            manager, mh, r.json["record"], "cancel", "leave-scope-approved-cancel"
        ).status_code
        == 409
    )
    pending = create(own, oh, parent, "leave-scope-pending", "2026-11-10", "2026-11-11")
    assert (
        action(own, oh, pending, "cancel", "leave-scope-own-cancel").status_code == 200
    )
    assert (
        action(own, oh, pending, "cancel", "leave-scope-own-cancel").status_code == 200
    )
    create(own, oh, parent, "leave-scope-replace", "2026-11-10", "2026-11-11")


def test_ambiguous_legacy_leave_requires_reference_review_before_approval(app):
    c, h = session(app)
    parent = employee(c, h, "leave-ambiguous-parent")
    with app.app_context():
        valid = {k: set() for k in hr.MODELS}
        valid["user"] = {"admin"}
        duplicate = {k: v for k, v in parent.items() if k != "version"}
        duplicate["id"] = "ambiguous-leave-employee"
        e = hr.Employee(id=duplicate["id"])
        hr.write_one("employees", duplicate, e, 1, valid, [])
        db.session.add(e)
        value = {
            "id": "ambiguous-leave",
            "employee": parent["employeeId"] + " - " + parent["name"],
            "from": "2026-11-01",
            "to": "2026-11-03",
            "leaveType": "Annual",
            "days": 3,
            "status": "Pending",
            "reason": "Legacy",
            "createdBy": "admin",
        }
        row = hr.Leave(id=value["id"])
        hr.write_one("leaves", value, row, 0, valid, [])
        db.session.add(row)
        db.session.commit()
    row = c.get("/api/hr/records/leaves/ambiguous-leave").json["record"]
    assert action(c, h, row, "approve", "ambiguous-leave-approve").status_code == 409
    assert action(c, h, row, "reject", "ambiguous-leave-reject").status_code == 200
    with app.app_context():
        assert db.session.get(hr.Leave, "ambiguous-leave").employee_id is None
