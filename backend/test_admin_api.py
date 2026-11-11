"""Administration credentials, session revocation, versions and compact SQL access."""

from copy import deepcopy
from sqlalchemy import select, func
from werkzeug.security import check_password_hash
from backend.test_app import app, session, PASSWORD
from backend.app import db, User, Document, Audit, LoginSession
from backend.admin_api import Command

counter = 0


def cmd(c, h, kind, expected=200, **d):
    global counter
    counter += 1
    r = c.post(
        "/api/administration/commands/" + kind,
        headers=h,
        json={"requestKey": "admin-test-" + str(counter), **d},
    )
    assert r.status_code == expected, r.json
    return r.json


def create(c, h, **d):
    data = dict(
        name="Native user",
        email="native@example.test",
        role="Viewer",
        active=True,
        password=PASSWORD,
    )
    data.update(d)
    return cmd(c, h, "create-user", **data)["record"]


def detail(c, id):
    return c.get("/api/administration/users/" + id).json["record"]


def edit(c, h, u, expected=200, **d):
    data = {k: u[k] for k in ("name", "email", "role", "active", "managerId")}
    data.update(d)
    return cmd(c, h, "edit-user", expected, id=u["id"], version=u["version"], **data)


def test_native_admin_user_credentials_sessions_and_replay(app):
    c, h = session(app)
    u = create(c, h, requestKey="admin-create-replay")
    assert create(c, h, requestKey="admin-create-replay")["id"] == u["id"]
    cmd(
        c,
        h,
        "create-user",
        409,
        requestKey="admin-create-replay",
        name="Native user",
        email="native@example.test",
        role="Viewer",
        active=True,
        password="A-different-password-42",
    )
    login = app.test_client()
    r = login.post("/api/auth/login", json={"email": u["email"], "password": PASSWORD})
    assert r.status_code == 200
    with app.app_context():
        stored = db.session.get(User, u["id"])
        assert check_password_hash(stored.password_hash, PASSWORD)
        assert PASSWORD not in str(db.session.scalars(select(Command)).all())
        assert all(
            PASSWORD not in str(a.details) for a in db.session.scalars(select(Audit))
        )
    changed = edit(c, h, u, name="Updated user")["record"]
    assert changed["version"] != u["version"]
    assert login.get("/api/auth/me").status_code == 401
    edit(c, h, u, 409, name="Stale")
    password = "Changed-native-password-42"
    changed = cmd(
        c,
        h,
        "password",
        id=changed["id"],
        version=changed["version"],
        password=password,
        confirmPassword=password,
        requestKey="admin-reset-replay",
    )["record"]
    assert (
        cmd(
            c,
            h,
            "password",
            id=changed["id"],
            version="old",
            password=password,
            confirmPassword=password,
            requestKey="admin-reset-replay",
        )["record"]["id"]
        == changed["id"]
    )
    assert (
        login.post(
            "/api/auth/login", json={"email": u["email"], "password": password}
        ).status_code
        == 200
    )
    changed = edit(c, h, changed, active=False)["record"]
    assert not changed["active"]
    assert login.get("/api/auth/me").status_code == 401
    assert (
        login.post(
            "/api/auth/login", json={"email": u["email"], "password": password}
        ).status_code
        == 401
    )
    assert "password" not in str(c.get("/api/administration/users").json).lower()


def test_admin_validation_self_and_manager_cycles(app):
    c, h = session(app)
    u = create(c, h, managerId="manager")
    manager = detail(c, "manager")
    edit(c, h, manager, 400, managerId=u["id"])
    edit(c, h, u, 400, managerId=u["id"])
    edit(c, h, u, 400, managerId="missing")
    edit(c, h, u, 400, role="Salesperson", managerId=None)
    edit(c, h, u, 400, active="yes")
    admin = detail(c, "admin")
    edit(c, h, admin, 400, active=False)
    edit(c, h, admin, 400, role="Viewer")
    cmd(
        c,
        h,
        "edit-user",
        428,
        id=u["id"],
        name="No version",
        email=u["email"],
        role="Viewer",
    )
    cmd(
        c,
        h,
        "create-user",
        409,
        name="Duplicate",
        email=u["email"],
        role="Viewer",
        password=PASSWORD,
    )
    cmd(
        c,
        h,
        "create-user",
        400,
        name="Bad",
        email="invalid",
        role="Viewer",
        password=PASSWORD,
    )
    cmd(
        c,
        h,
        "create-user",
        400,
        name="Bad",
        email="bad@example.test",
        role="Viewer",
        password="short",
    )
    cmd(
        c,
        h,
        "password",
        400,
        id=u["id"],
        version=u["version"],
        password=PASSWORD,
        confirmPassword="mismatch",
    )
    cmd(c, h, "edit-user", 400, id=u["id"], version=u["version"], password=PASSWORD)


def test_role_normalization_revocation_and_config_preservation(app):
    c, h = session(app)
    viewer, vh = session(app, "viewer")
    with app.app_context():
        before = deepcopy(db.session.get(Document, "app").stored_data)
    r = c.get("/api/administration/roles/Viewer").json["record"]
    old = deepcopy(r)
    r["permissions"]["expenses"]["view"] = False
    r["permissions"]["expenses"]["approve"] = True
    saved = cmd(
        c, h, "role", name="Viewer", version=r["version"], permissions=r["permissions"]
    )["record"]
    assert not any(saved["permissions"]["expenses"].values())
    assert viewer.get("/api/auth/me").status_code == 401
    cmd(
        c,
        h,
        "role",
        409,
        name="Viewer",
        version=old["version"],
        permissions=old["permissions"],
    )
    cmd(c, h, "role", 400, name="Admin", version="irrelevant", permissions={})
    cmd(c, h, "role", 400, name="Viewer", version=saved["version"], permissions={})
    with app.app_context():
        after = db.session.get(Document, "app").stored_data
        assert {k: v for k, v in before.items() if k != "roles"} == {
            k: v for k, v in after.items() if k != "roles"
        }
        assert before["roles"]["Finance"] == after["roles"]["Finance"]


def test_company_version_fixed_localization_and_no_rewrite(app):
    c, h = session(app)
    r = c.get("/api/administration/company").json["record"]
    with app.app_context():
        before = deepcopy(db.session.get(Document, "app").stored_data)
    values = dict(
        name="Client demo",
        legalName="Demo legal",
        address="Karachi",
        phone="123",
        email="demo@example.test",
        taxNumber="demo",
    )
    new = cmd(c, h, "company", version=r["version"], **values)["record"]
    assert new["values"]["currency"] == "PKR" and new["values"]["country"] == "Pakistan"
    assert new["values"]["name"] == "Client demo"
    cmd(c, h, "company", 409, version=r["version"], **values)
    cmd(c, h, "company", 400, version=new["version"], currency="USD", **values)
    with app.app_context():
        after = db.session.get(Document, "app").stored_data
        assert {k: v for k, v in before.items() if k != "company"} == {
            k: v for k, v in after.items() if k != "company"
        }


def test_admin_privacy_audit_own_scope_and_pagination(app):
    c, h = session(app)
    seller, sh = session(app, "seller")
    manager, mh = session(app, "manager")
    for who in (seller, manager):
        for path in ("users", "roles", "company", "summary", "managers"):
            assert who.get("/api/administration/" + path).status_code == 403
    cmd(seller, sh, "company", 403, version="bad", name="No")
    with app.app_context():
        for i in range(30):
            db.session.add(
                Audit(
                    actor_id="seller",
                    action="Own activity " + str(i),
                    details={"safe": True},
                    at="2026-10-28T01:00:00+00:00",
                )
            )
        db.session.add(
            Audit(
                actor_id="manager",
                action="Manager private activity",
                details={},
                at="2026-10-28T01:00:00+00:00",
            )
        )
        db.session.commit()
    r = seller.get("/api/administration/activities?page=2").json
    assert (
        r["total"] == 31
        and len(r["items"]) == 6
        and all(x["actorId"] == "seller" for x in r["items"])
    )
    assert manager.get("/api/administration/activities?search=Own").json["total"] == 0
    assert (
        seller.get("/api/administration/activities?search=Own%20activity%202").json[
            "total"
        ]
        == 11
    )
    assert (
        c.get("/api/administration/activities?from=2026-10-28&to=2026-10-28").json[
            "total"
        ]
        >= 31
    )
    assert (
        c.get(
            "/api/administration/activities?from=2026-10-29&to=2026-10-28"
        ).status_code
        == 400
    )
    assert c.get("/api/administration/users?pageSize=2").json["total"] == 5
    assert len(c.get("/api/administration/users?pageSize=2").json["items"]) == 2
    assert c.get("/api/administration/users?search=seller").json["total"] == 1
    assert c.get("/api/administration/managers?exclude=admin").json["total"] == 4
    assert c.get("/api/administration/users?active=invalid").status_code == 400


def test_admin_compact_operations_and_repeat_upgrade(app, monkeypatch):
    c, h = session(app)
    original = Document.data.fget

    def bounded(doc):
        assert doc.name not in ("app", "hr"), "Aggregate projection"
        return original(doc)

    monkeypatch.setattr(Document, "data", property(bounded, Document.data.fset))
    for path in ("users", "roles", "company", "summary", "managers", "activities"):
        assert c.get("/api/administration/" + path).status_code == 200
    u = create(c, h)
    u = edit(c, h, u, name="Bounded update")["record"]
    cmd(
        c,
        h,
        "password",
        id=u["id"],
        version=u["version"],
        password=PASSWORD,
        confirmPassword=PASSWORD,
    )
    r = c.get("/api/administration/company").json["record"]
    cmd(c, h, "company", version=r["version"], name="Compact company")
    r = c.get("/api/administration/roles/Viewer").json["record"]
    cmd(
        c, h, "role", name=r["name"], version=r["version"], permissions=r["permissions"]
    )
    monkeypatch.undo()
    with app.app_context():
        count = db.session.scalar(select(func.count()).select_from(User))
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(User)) == count


def test_self_password_reset_requires_fresh_login(app):
    c, h = session(app)
    u = detail(c, "admin")
    new = "New-admin-password-42"
    r = cmd(
        c,
        h,
        "password",
        id=u["id"],
        version=u["version"],
        password=new,
        confirmPassword=new,
    )
    assert r["signInRequired"] is True
    assert c.get("/api/auth/me").status_code == 401
    assert (
        c.post(
            "/api/auth/login", json={"email": "admin@example.test", "password": new}
        ).status_code
        == 200
    )
