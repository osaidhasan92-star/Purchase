"""Native HR simulations with financial, visibility and migration invariants."""

from copy import deepcopy
import pytest
from sqlalchemy import select, func
from backend.test_app import app, session, PASSWORD
from backend.app import db, Document, User, LoginSession, Audit
from backend.erp import JournalEntry, JournalLine
from backend import hr_store as store


@pytest.fixture(autouse=True)
def transport(app):
    app.config["ENABLE_LEGACY_HR_WRITES"] = False


counter = 0


def post(client, h, key, data, expected=200):
    global counter
    counter += 1
    payload = {"requestKey": "hr-test-" + str(counter), **data}
    r = client.post("/api/hr/records/" + key, headers=h, json=payload)
    assert r.status_code == expected, r.json
    return r.json.get("record")


def employee(client, h, **extra):
    return post(
        client,
        h,
        "employees",
        dict(
            employeeId="EMP-1",
            name="Payroll Employee",
            department="Production",
            designation="Operator",
            joiningDate="2026-10-01",
            salary=10000,
            **extra
        ),
    )


def action(c, h, key, row, act, expected=200):
    return post(
        c,
        h,
        key + "/" + str(row["id"]) + "/actions/" + act,
        dict(version=row["version"]),
        expected,
    )


def payroll(c, h, e, **extra):
    return post(
        c,
        h,
        "payroll",
        dict(
            employeeKey=e["id"],
            month="2026-10",
            basic=10000,
            allowances=500,
            deductions=100,
            **extra
        ),
    )


def test_payroll_full_posting_idempotency_and_immutability(app):
    c, h = session(app)
    e = employee(c, h)
    p = payroll(c, h, e)
    assert p["netPay"] == 10400
    payload = dict(requestKey="approve-payroll-repeat", version=p["version"])
    url = "/api/hr/records/payroll/" + p["id"] + "/actions/approve"
    r = c.post(url, headers=h, json=payload)
    assert r.status_code == 200, r.json
    p = r.json["record"]
    assert p["status"] == "Approved"
    assert c.post(url, headers=h, json=payload).status_code == 200
    assert (
        c.patch(
            "/api/hr/records/payroll/" + p["id"],
            headers=h,
            json=dict(version=p["version"], requestKey="edit-posted-payroll", basic=1),
        ).status_code
        == 409
    )
    p = action(c, h, "payroll", p, "pay")
    assert p["status"] == "Paid"
    assert c.get("/api/hr/records/payroll/" + p["id"] + "/print").status_code == 200
    with app.app_context():
        entries = db.session.scalars(
            select(JournalEntry).where(JournalEntry.source.like("payroll:%"))
        ).all()
        assert len(entries) == 2
        for entry in entries:
            lines = db.session.scalars(
                select(JournalLine).where(JournalLine.entry_id == entry.id)
            ).all()
            assert sum(x.debit for x in lines) == sum(x.credit for x in lines)
        balances = {
            account: sum(
                x.debit - x.credit
                for entry in entries
                for x in entry.lines
                if x.account == account
            )
            for account in ("6100", "2300", "2310", "1010")
        }
        assert balances == {"6100": 10500, "2300": 0, "2310": -100, "1010": -10400}
        assert db.session.scalar(select(func.count()).select_from(store.Payroll)) == 1
        assert "payroll" not in db.session.get(Document, "hr").stored_data


def test_validation_duplicates_overlap_and_unknown_fields(app):
    c, h = session(app)
    e = employee(c, h)
    post(
        c,
        h,
        "employees",
        dict(
            employeeId="emp-1",
            name="Other",
            department="HR",
            designation="X",
            joiningDate="2026-10-01",
        ),
        409,
    )
    payroll(c, h, e)
    post(c, h, "payroll", dict(employeeKey=e["id"], month="2026-10", basic=1), 409)
    post(
        c,
        h,
        "payroll",
        dict(employeeKey=e["id"], month="2026-11", basic=10, deductions=11),
        400,
    )
    post(c, h, "payroll", dict(employeeKey=e["id"], month="2026-13", basic=10), 400)
    post(
        c,
        h,
        "payroll",
        dict(employeeKey=e["id"], month="2026-12", basic=10, netPay=999),
        400,
    )
    a = post(
        c,
        h,
        "attendance",
        dict(employeeKey=e["id"], date="2026-10-26", attendanceStatus="Present"),
    )
    post(
        c,
        h,
        "attendance",
        dict(employeeKey=e["id"], date="2026-10-26", attendanceStatus="Late"),
        409,
    )
    leave = post(
        c,
        h,
        "leaves",
        dict(
            employeeKey=e["id"],
            leaveType="Annual",
            **{"from": "2026-11-01", "to": "2026-11-02"},
            reason="Holiday"
        ),
    )
    assert leave["days"] == 2
    post(
        c,
        h,
        "leaves",
        dict(
            employeeKey=e["id"],
            leaveType="Annual",
            **{"from": "2026-11-02", "to": "2026-11-03"},
            reason="Overlap"
        ),
        409,
    )
    leave = action(c, h, "leaves", leave, "reject")
    post(
        c,
        h,
        "leaves",
        dict(
            employeeKey=e["id"],
            leaveType="Sick",
            **{"from": "2026-11-02", "to": "2026-11-03"},
            reason="Rest"
        ),
    )


def test_versions_keys_and_legacy_transport(app):
    c, h = session(app)
    e = employee(c, h)
    url = "/api/hr/records/employees/" + e["id"]
    assert (
        c.patch(
            url, headers=h, json=dict(name="Changed", requestKey="missing-version")
        ).status_code
        == 428
    )
    r = c.patch(
        url,
        headers=h,
        json=dict(name="Changed", version=e["version"], requestKey="correct-version"),
    )
    assert r.status_code == 200, r.json
    assert (
        c.patch(
            url,
            headers=h,
            json=dict(
                name="Conflict", version=e["version"], requestKey="stale-version"
            ),
        ).status_code
        == 409
    )
    post(
        c,
        h,
        "employees",
        dict(
            employeeId="EMP-2",
            name="Other",
            department="HR",
            designation="X",
            joiningDate="2026-10-01",
            requestKey="correct-version",
        ),
        409,
    )
    assert (
        c.patch(
            "/api/hr/state", headers=h, json=dict(revision=1, changes={"payroll": []})
        ).status_code
        == 410
    )


def test_permissions_self_manager_and_sql_paging(app):
    c, h = session(app)
    e = employee(c, h)
    with app.app_context():
        doc = db.session.get(Document, "hr")
        d = deepcopy(doc.data)
        d["employees"][0]["linkedUserId"] = "seller"
        doc.data = d
        appdoc = db.session.get(Document, "app")
        s = deepcopy(appdoc.data)
        for role in ("Salesperson", "Sales Manager", "Viewer"):
            for m in ("hr_employees", "hr_payroll", "hr_attendance", "hr_leave"):
                s["roles"][role]["permissions"][m] = dict(
                    view=True, create=True, edit=False, approve=False, export=True
                )
        appdoc.data = s
        db.session.commit()
    p = payroll(c, h, e)
    own, oh = session(app, "seller")
    manager, mh = session(app, "manager")
    other, vh = session(app, "viewer")
    for client in (own, manager):
        r = client.get("/api/hr/records/payroll?pageSize=1")
        assert r.status_code == 200, r.json
        assert r.json["total"] == 1
        assert client.get("/api/hr/records/payroll/" + p["id"]).status_code == 200
    assert other.get("/api/hr/records/payroll").json["items"] == []
    assert other.get("/api/hr/records/payroll/" + p["id"]).status_code == 404
    assert other.get("/api/hr/records/payroll/" + p["id"] + "/print").status_code == 404
    action(own, oh, "payroll", p, "approve", 403)
    assert "salary" not in str(own.get("/api/hr/employee-options/leaves").json)
    assert own.get("/api/hr/records/payroll?pageSize=101").status_code == 400
    post(
        other,
        vh,
        "attendance",
        dict(employeeKey=e["id"], date="2026-10-26", attendanceStatus="Present"),
        404,
    )


def test_login_creation_atomic_and_offboarding_revokes_sessions(app):
    c, h = session(app)
    e = employee(c, h)
    hr, hh = session(app, "hr")
    post(
        hr,
        hh,
        "employees/" + e["id"] + "/actions/login",
        dict(
            version=e["version"],
            email="new@example.test",
            role="Requester",
            password=PASSWORD,
        ),
        403,
    )
    e = post(
        c,
        h,
        "employees/" + e["id"] + "/actions/login",
        dict(
            version=e["version"],
            email="new@example.test",
            role="Requester",
            password=PASSWORD,
        ),
    )
    assert "password" not in str(e).lower()
    new = app.test_client()
    assert (
        new.post(
            "/api/auth/login", json=dict(email="new@example.test", password=PASSWORD)
        ).status_code
        == 200
    )
    sep = post(
        c,
        h,
        "separations",
        dict(
            employeeKey=e["id"],
            lastWorkingDate="2026-10-30",
            reason="Leaving",
            finalSettlement=0,
        ),
    )
    action(c, h, "separations", sep, "complete", 409)
    sep = action(c, h, "separations", sep, "approve")
    sep = action(c, h, "separations", sep, "complete")
    assert new.get("/api/auth/me").status_code == 401
    with app.app_context():
        assert not db.session.get(User, e["linkedUserId"]).active
        assert not db.session.scalar(
            select(LoginSession).where(LoginSession.user_id == e["linkedUserId"])
        )
        assert PASSWORD not in str(db.session.get(Document, "hr").stored_data)
        assert PASSWORD not in str(
            [a.details for a in db.session.scalars(select(Audit))]
        )
    assert (
        c.get("/api/hr/records/employees/" + e["id"]).json["record"]["status"]
        == "Separated"
    )
    post(
        c,
        h,
        "attendance",
        dict(employeeKey=e["id"], date="2026-11-01", attendanceStatus="Present"),
        400,
    )


def test_admin_offboarding_rolls_back_and_login_failure_has_no_orphan(app):
    c, h = session(app)
    e = employee(c, h)
    post(
        c,
        h,
        "employees/" + e["id"] + "/actions/login",
        dict(
            version=e["version"],
            email="bad@example.test",
            role="Missing",
            password=PASSWORD,
        ),
        400,
    )
    with app.app_context():
        assert not db.session.scalar(
            select(User).where(User.email == "bad@example.test")
        )
    with app.app_context():
        doc = db.session.get(Document, "hr")
        d = deepcopy(doc.data)
        d["employees"][0]["linkedUserId"] = "admin"
        doc.data = d
        db.session.commit()
    sep = post(
        c,
        h,
        "separations",
        dict(
            employeeKey=e["id"],
            lastWorkingDate="2026-10-30",
            reason="Admin exit",
            finalSettlement=0,
        ),
    )
    sep = action(c, h, "separations", sep, "approve")
    action(c, h, "separations", sep, "complete", 400)
    assert (
        c.get("/api/hr/records/employees/" + e["id"]).json["record"]["status"]
        == "Active"
    )
    assert (
        c.get("/api/hr/records/separations/" + sep["id"]).json["record"]["status"]
        == "Approved"
    )


def test_recruitment_headcount_to_onboarding(app):
    c, h = session(app)
    req = post(
        c,
        h,
        "manpower",
        dict(
            department="Production",
            position="Operator",
            count=2,
            reason="Expansion",
            requestedBy="Manager",
        ),
    )
    post(
        c,
        h,
        "candidates",
        dict(
            name="Candidate",
            position="Operator",
            contact="test@example.test",
            manpowerId=req["id"],
        ),
        400,
    )
    req = action(c, h, "manpower", req, "approve")
    candidate = post(
        c,
        h,
        "candidates",
        dict(
            name="Candidate",
            position="Operator",
            contact="test@example.test",
            manpowerId=req["id"],
        ),
    )
    action(c, h, "candidates", candidate, "offer", 409)
    for act in ("shortlist", "interview", "select", "offer"):
        candidate = action(c, h, "candidates", candidate, act)
    e = employee(c, h, candidateId=candidate["id"])
    assert (
        c.get("/api/hr/records/candidates/" + candidate["id"]).json["record"]["stage"]
        == "Hired"
    )
    post(
        c,
        h,
        "employees",
        dict(
            employeeId="EMP-2",
            name="Duplicate hire",
            department="P",
            designation="O",
            joiningDate="2026-10-01",
            candidateId=candidate["id"],
        ),
        400,
    )


def test_migrate_existing_hr_exact_and_no_reposting(app):
    c, h = session(app)
    e = employee(c, h)
    p = payroll(c, h, e)
    p = action(c, h, "payroll", p, "approve")
    with app.app_context():
        doc = db.session.get(Document, "hr")
        original = deepcopy(doc.data)
        original["employees"][0]["customField"] = {"preserve": ["all", 1, None]}
        # Represent the pre-migration aggregate; preserve existing ledger/source IDs.
        doc.stored_data = original
        db.session.commit()
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert not db.session.get(Document, "hr").stored_data.get(store.MARKER)
    result = app.test_cli_runner().invoke(args=["migrate-storage"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        doc = db.session.get(Document, "hr")
        assert doc.data == original
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(JournalEntry)
                .where(JournalEntry.source.like("payroll:%"))
            )
            == 1
        )
        rev = doc.revision
    assert app.test_cli_runner().invoke(args=["migrate-storage"]).exit_code == 0
    with app.app_context():
        assert db.session.get(Document, "hr").revision == rev
    action(
        c,
        h,
        "payroll",
        c.get("/api/hr/records/payroll/" + p["id"]).json["record"],
        "pay",
    )


def test_migrate_unresolved_refs_and_legacy_label_visibility(app):
    c, h = session(app)
    old = {key: [] for key in store.MODELS}
    old["employees"] = [
        dict(
            id=12,
            employeeId="EMP-OLD",
            name="Legacy",
            linkedUserId="seller",
            salary="123.4567",
            status="Active",
        )
    ]
    old["attendance"] = [
        dict(
            id="att-old",
            employee="EMP-OLD - Legacy",
            date="2026-10-01",
            attendanceStatus="Present",
        )
    ]
    old["payroll"] = [
        dict(
            id="orphan",
            employeeKey="missing",
            employee="Missing",
            month="2026-09",
            basic=1,
            netPay=1,
            status="Draft",
        )
    ]
    old["employees"].extend(
        [
            dict(
                id=13,
                employeeId="DUP",
                name="Ambiguous",
                linkedUserId="seller",
                status="Active",
            ),
            dict(
                id=14,
                employeeId="DUP",
                name="Ambiguous",
                linkedUserId="manager",
                status="Active",
            ),
        ]
    )
    old["attendance"].append(
        dict(
            id="att-ambiguous",
            employee="DUP - Ambiguous",
            date="2026-10-02",
            attendanceStatus="Present",
        )
    )
    old["payroll"].append(
        dict(
            id="pay-ambiguous",
            employee="DUP - Ambiguous",
            month="2026-09",
            basic=1,
            netPay=1,
            status="Draft",
        )
    )
    old["candidates"] = [
        dict(
            id="legacy-offer",
            name="Offered before migration",
            position="Operator",
            contact="legacy@example.test",
            status="Pending",
            stage="Offer Issued",
        )
    ]
    with app.app_context():
        doc = db.session.get(Document, "hr")
        doc.stored_data = old
        db.session.commit()
    assert app.test_cli_runner().invoke(args=["migrate-storage"]).exit_code == 0
    with app.app_context():
        assert db.session.get(Document, "hr").data == old
        assert db.session.get(store.Attendance, "att-old").employee_id == "12"
        assert db.session.get(store.Payroll, "orphan").employee_id is None
        assert db.session.get(store.Attendance, "att-ambiguous").employee_id is None
    assert (
        c.get("/api/hr/records/candidates?status=Offer%20Issued").json["items"][0]["id"]
        == "legacy-offer"
    )
    action(
        c,
        h,
        "payroll",
        c.get("/api/hr/records/payroll/pay-ambiguous").json["record"],
        "approve",
        409,
    )
    action(
        c,
        h,
        "payroll",
        c.get("/api/hr/records/payroll/orphan").json["record"],
        "approve",
        409,
    )


def test_csv_filtering_and_formula_escaping(app):
    c, h = session(app)
    e = employee(c, h)
    with app.app_context():
        doc = db.session.get(Document, "hr")
        d = deepcopy(doc.data)
        d["employees"][0]["employeeId"] = "=formula"
        doc.data = d
        db.session.commit()
    post(
        c,
        h,
        "attendance",
        dict(employeeKey=e["id"], date="2026-10-26", attendanceStatus="Present"),
    )
    r = c.get("/api/hr/records/attendance/export?pageSize=1")
    assert r.status_code == 200
    assert "'=formula" in r.text
    assert (
        c.get("/api/hr/records/attendance/export?search=NoMatch").text.count("\n") == 1
    )
