"""Native CRM privacy, relational persistence and Sales compatibility."""

from backend.test_app import app, session, patch, PASSWORD
from backend.app import db, Document
from backend.master_store import Lead, Reminder


def seed(client, h):
    result = client.post(
        "/api/customers",
        headers=h,
        json={"name": "CRM customer", "requestKey": "crm-customer-seed"},
    )
    assert result.status_code == 200, result.json
    return result.json["customer"]


def lead(client, h, customer, **fields):
    response = client.post(
        "/api/crm/leads",
        headers=h,
        json=dict(customerId=customer["id"], requestKey="crm-lead-001", **fields),
    )
    assert response.status_code == 200, response.json
    return response.json["record"]


def test_crm_private_assignment_manager_scope_and_sales_handoff(app):
    admin, h = session(app)
    customer = seed(admin, h)
    private = lead(
        admin, h, customer, ownerId="seller", stage="Quotation Required", value=100
    )
    seller, sh = session(app, "seller")
    manager, _ = session(app, "manager")
    viewer, vh = session(app, "viewer")
    assert seller.get("/api/crm/leads").json["items"][0]["id"] == private["id"]
    assert manager.get("/api/crm/leads").json["total"] == 1
    assert viewer.get("/api/crm/leads").json["total"] == 0
    assert (
        viewer.patch(
            "/api/crm/leads/" + str(private["id"]),
            headers=vh,
            json={"version": private["version"], "notes": "Stolen"},
        ).status_code
        == 403
    )
    # The full old Sales screen still sees the assigned SQL lead and linked customer.
    legacy = seller.get("/api/state").json["state"]
    assert legacy["leads"][0]["customerId"] == customer["id"]
    assert legacy["leads"][0]["stage"] == "Quotation Required"
    edited = seller.patch(
        "/api/crm/leads/" + str(private["id"]),
        headers=sh,
        json={"version": private["version"], "contact": "Sales contact"},
    )
    assert edited.status_code == 200, edited.json
    assert edited.json["record"]["createdBy"] == "admin"
    assert (
        seller.patch(
            "/api/crm/leads/" + str(private["id"]),
            headers=sh,
            json={"version": private["version"], "value": 200},
        ).status_code
        == 409
    )
    assert (
        seller.patch(
            "/api/crm/leads/" + str(private["id"]),
            headers=sh,
            json={"version": edited.json["record"]["version"], "stage": "Closed Won"},
        ).status_code
        == 400
    )
    with app.app_context():
        assert db.session.get(Lead, str(private["id"])).owner_id == "seller"
        assert "leads" not in db.session.get(Document, "app").stored_data


def test_crm_reminder_permissions_and_summary_do_not_leak(app):
    admin, h = session(app)
    customer = seed(admin, h)
    private = lead(admin, h, customer, ownerId="seller", value=100)
    response = admin.post(
        "/api/crm/reminders",
        headers=h,
        json={
            "leadId": private["id"],
            "dueDate": "2020-01-01",
            "requestKey": "crm-reminder-seed",
        },
    )
    assert response.status_code == 200, response.json
    reminder = response.json["record"]
    seller, sh = session(app, "seller")
    viewer, _ = session(app, "viewer")
    assert seller.get("/api/crm/reminders").json["total"] == 1
    assert viewer.get("/api/crm/reminders").json["total"] == 0
    assert viewer.get("/api/crm/summary").json["pipeline"] == 0
    summary = seller.get("/api/crm/summary").json
    assert summary["pipeline"] == 100 and len(summary["due"]) == 1
    completed = seller.patch(
        "/api/crm/reminders/" + str(reminder["id"]),
        headers=sh,
        json={"version": reminder["version"], "done": True},
    )
    assert completed.status_code == 200, completed.json
    assert seller.get("/api/crm/summary").json["due"] == []
    with app.app_context():
        assert db.session.get(Reminder, str(reminder["id"])).done


def test_crm_native_validation_idempotency_and_reference_access(app):
    admin, h = session(app)
    customer = seed(admin, h)
    private = lead(admin, h, customer, value=10)
    assert lead(admin, h, customer, value=10)["id"] == private["id"]
    seller, sh = session(app, "seller")
    # An ID from another CRM team cannot become a reminder reference.
    assert (
        seller.post(
            "/api/crm/reminders",
            headers=sh,
            json={
                "leadId": private["id"],
                "dueDate": "2026-10-27",
                "requestKey": "steal-reminder-ref",
            },
        ).status_code
        == 404
    )
    for values in (
        {"customerId": "missing"},
        {"value": -1},
        {"stage": "Closed Won"},
        {"currency": "USD"},
        {"email": "bad"},
        {"expectedClose": "bad-date"},
        {"createdBy": "viewer"},
    ):
        response = admin.post(
            "/api/crm/leads",
            headers=h,
            json={
                "customerId": customer["id"],
                "requestKey": "bad-crm-request",
                **values,
            },
        )
        assert response.status_code == 400, response.json
    assert (
        seller.post(
            "/api/crm/leads",
            headers=sh,
            json={
                "customerId": customer["id"],
                "ownerId": "admin",
                "requestKey": "forged-assignment",
            },
        ).status_code
        == 403
    )
    hr, _ = session(app, "hr")
    assert hr.get("/api/crm/leads").status_code == 403
    assert (
        admin.get("/api/crm/leads?search=crm%20customer&pageSize=1").json["total"] == 1
    )


def test_crm_manager_assignment_directory_is_limited_and_legacy_updates_sql(app):
    admin, h = session(app)
    customer = seed(admin, h)
    user = admin.post(
        "/api/users",
        headers=h,
        json={
            "name": "CRM lead",
            "email": "crm@example.test",
            "role": "CRM Manager",
            "password": PASSWORD,
            "active": True,
        },
    )
    assert user.status_code == 200
    crm = app.test_client()
    login = crm.post(
        "/api/auth/login", json={"email": "crm@example.test", "password": PASSWORD}
    )
    ch = {"X-CSRF-Token": login.json["csrfToken"]}
    assignees = crm.get("/api/crm/assignees").json["items"]
    assert any(u["id"] == "seller" for u in assignees)
    assert all(set(u) == {"id", "name", "role", "managerId"} for u in assignees)
    created = lead(crm, ch, customer, ownerId="seller")
    seller, sh = session(app, "seller")
    legacy = seller.get("/api/state").json["state"]["leads"]
    legacy[0]["source"] = "Legacy handoff"
    assert patch(seller, sh, {"leads": legacy}).status_code == 200
    assert seller.get("/api/crm/leads").json["items"][0]["source"] == "Legacy handoff"
    assert (
        crm.patch(
            "/api/crm/leads/" + str(created["id"]),
            headers=ch,
            json={"version": created["version"], "source": "Stale"},
        ).status_code
        == 409
    )
