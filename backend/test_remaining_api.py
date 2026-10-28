"""Final native screens: exact register migration, privacy and compact overview."""

from copy import deepcopy
from decimal import Decimal
from sqlalchemy import select, func
from backend.test_app import app, session
from backend.app import db, Document, User
from backend.crm_register_store import Company, Quote, MARKER, read
from backend.erp import JournalEntry

counter = 0


def save(c, h, key, data, id=None, expected=200):
    global counter
    counter += 1
    r = c.open(
        "/api/crm-registers/" + key + ("/" + str(id) if id else ""),
        method="PATCH" if id else "POST",
        headers=h,
        json={"requestKey": "register-test-" + str(counter), **data},
    )
    assert r.status_code == expected, r.json
    return r.json.get("record")


def grant(app):
    with app.app_context():
        d = db.session.get(Document, "app")
        s = deepcopy(d.stored_data)
        for role in ("Salesperson", "Sales Manager", "HR Manager"):
            for key in ("companies", "crmQuotes", "leads"):
                s["roles"][role]["permissions"][key] = {
                    a: True for a in ("view", "create", "edit", "approve", "export")
                }
                s["roles"][role][key] = True
        d.stored_data = s
        db.session.commit()


def lead(c, h, name="Lead customer"):
    global counter
    counter += 1
    customer = c.post(
        "/api/customers",
        headers=h,
        json={"name": name, "requestKey": "register-customer-" + str(counter)},
    ).json["customer"]
    r = c.post(
        "/api/crm/leads",
        headers=h,
        json={
            "customerId": customer["id"],
            "stage": "New",
            "value": 100,
            "currency": "PKR",
            "requestKey": "register-lead-" + str(counter),
        },
    )
    assert r.status_code == 200, r.json
    return r.json["record"]


def quote(c, h, l, **extra):
    return save(
        c,
        h,
        "crmQuotes",
        dict(
            leadId=l["id"],
            amount=25,
            currency="PKR",
            quoteDate="2026-10-28",
            validUntil="2026-11-28",
            status="Draft",
            **extra
        ),
    )


def test_crm_register_roundtrip_upgrade_and_no_reposting(app):
    with app.app_context():
        doc = db.session.get(Document, "app")
        stored = deepcopy(doc.stored_data)
        stored.pop(MARKER)
        original = {
            "companies": [
                {
                    "id": 7,
                    "name": "Historical company",
                    "status": None,
                    "custom": {"x": 1},
                }
            ],
            "crmQuotes": [
                {
                    "id": "old-q",
                    "quoteNo": "H-1",
                    "leadId": 999,
                    "amount": "12.3400",
                    "currency": "USD",
                    "ownerId": "seller",
                    "companyName": "Old snapshot",
                    "custom": True,
                }
            ],
        }
        stored.update(original)
        doc.stored_data = stored
        db.session.commit()
    c, h = session(app)
    assert c.get("/api/overview/summary").json["canSeed"] is False
    assert c.post("/api/erp/seed-demo", headers=h, json={}).status_code == 400
    runner = app.test_cli_runner()
    r = runner.invoke(args=["migrate-storage"])
    assert r.exit_code == 0, r.output
    with app.app_context():
        doc = db.session.get(Document, "app")
        assert doc.stored_data[MARKER] == 1
        for k, v in original.items():
            assert read(k) == v and k not in doc.stored_data
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 0
    assert runner.invoke(args=["migrate-storage"]).exit_code == 0
    with app.app_context():
        assert read("crmQuotes") == original["crmQuotes"]


def test_crm_register_migration_rollback(app):
    with app.app_context():
        doc = db.session.get(Document, "app")
        s = deepcopy(doc.stored_data)
        s.pop(MARKER)
        s.update(
            companies=[{"id": 1, "name": "Keep me"}],
            crmQuotes=[{"id": 2, "amount": "not-money"}],
        )
        doc.stored_data = s
        db.session.commit()
    r = app.test_cli_runner().invoke(args=["migrate-storage"])
    assert r.exit_code != 0
    with app.app_context():
        doc = db.session.get(Document, "app")
        assert not doc.stored_data.get(MARKER)
        assert doc.stored_data["companies"][0]["name"] == "Keep me"
        assert db.session.scalar(select(func.count()).select_from(Company)) == 0


def test_crm_quote_scope_sources_status_and_no_economic_effect(app):
    grant(app)
    owner, h = session(app, "seller")
    manager, mh = session(app, "manager")
    other, oh = session(app, "hr")
    admin, ah = session(app)
    l = lead(owner, h)
    q = quote(owner, h, l)
    assert manager.get("/api/crm-registers/crmQuotes").json["total"] == 1
    assert other.get("/api/crm-registers/crmQuotes").json["total"] == 0
    assert other.get("/api/crm-registers/crmQuotes/" + q["id"]).status_code == 404
    quote_other = dict(leadId=l["id"], amount=25)
    save(other, oh, "crmQuotes", quote_other, expected=400)
    q = save(
        owner, h, "crmQuotes", {"version": q["version"], "status": "Accepted"}, q["id"]
    )
    assert q["createdBy"] == "seller"
    assert admin.get("/api/crm-registers/crmQuotes").json["total"] == 1
    with app.app_context():
        from backend.master_store import Lead

        assert db.session.get(Lead, str(l["id"])).stage == "New"
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 0
    assert other.get("/api/crm-registers/lead-options").json["total"] == 0


def test_crm_register_versions_replay_validation_and_paging(app):
    c, h = session(app)
    l = lead(c, h)
    q = quote(c, h, l)
    old = deepcopy(q)
    save(c, h, "crmQuotes", {"status": "Sent"}, q["id"], 428)
    q = save(c, h, "crmQuotes", {"version": q["version"], "status": "Sent"}, q["id"])
    save(
        c,
        h,
        "crmQuotes",
        {"version": old["version"], "status": "Rejected"},
        q["id"],
        409,
    )
    for extra in (
        {"amount": -1},
        {"currency": "USD"},
        {"validUntil": "2026-01-01"},
        {"status": "Won"},
        {"createdBy": "seller"},
    ):
        values = dict(leadId=l["id"], amount=1, quoteDate="2026-10-28")
        values.update(extra)
        save(c, h, "crmQuotes", values, expected=400)
    values = dict(name="Company", requestKey="company-idempotency")
    one = save(c, h, "companies", values)
    assert save(c, h, "companies", values)["id"] == one["id"]
    save(c, h, "companies", {**values, "name": "Other"}, expected=409)
    for i in range(26):
        save(c, h, "companies", dict(name="Paged " + str(i), industry="General"))
    r = c.get("/api/crm-registers/companies?page=2").json
    assert r["total"] == 27 and len(r["items"]) == 2
    assert c.get("/api/crm-registers/companies?search=Paged").json["total"] == 26
    assert c.get("/api/crm-registers/companies?page=0").status_code == 400


def test_overview_permission_filtered_totals_and_seed(app):
    c, h = session(app)
    assert c.get("/api/overview/summary").json["canSeed"] is True
    assert c.post("/api/erp/seed-demo", headers=h, json={}).status_code == 200
    r = c.get("/api/overview/summary").json
    assert Decimal(r["cashBank"]) == 275000 and Decimal(r["inventoryValue"]) == 60000
    assert r["canSeed"] is False
    seller, sh = session(app, "seller")
    r = seller.get("/api/overview/summary").json
    assert "cashBank" not in r and "profit" not in r and "openProduction" not in r
    assert r["canSeed"] is False
    assert seller.post("/api/erp/seed-demo", headers=sh, json={}).status_code == 403
    assert c.post("/api/erp/seed-demo", headers=h, json={}).status_code == 400


def test_registers_permissions_and_legacy_currency_preservation(app):
    c, h = session(app)
    company = save(c, h, "companies", {"name": "Existing company"})
    assert c.get("/api/overview/summary").json["canSeed"] is False
    assert c.post("/api/erp/seed-demo", headers=h, json={}).status_code == 400
    assert (
        c.get("/api/crm-registers/companies/" + company["id"]).json["record"]["name"]
        == "Existing company"
    )
    seller, sh = session(app, "seller")
    assert seller.get("/api/crm-registers/companies").status_code == 403
    viewer, vh = session(app, "viewer")
    save(viewer, vh, "companies", dict(name="No"), expected=403)
    with app.app_context():
        from backend.crm_register_store import write_one

        write_one(
            "crmQuotes",
            dict(
                id=12,
                quoteNo="USD-old",
                currency="USD",
                amount=5,
                leadId="missing",
                createdBy="admin",
                companyName="Historical",
            ),
            0,
        )
        db.session.commit()
    r = c.get("/api/crm-registers/crmQuotes/12")
    assert r.status_code == 200 and r.json["record"]["currency"] == "USD"
    save(
        c,
        h,
        "crmQuotes",
        {"version": r.json["record"]["version"], "status": "Sent"},
        12,
        400,
    )
    assert c.get("/api/crm-registers/lead-options").json["total"] == 0


def test_new_native_reads_and_writes_never_project_aggregates(app, monkeypatch):
    c, h = session(app)
    l = lead(c, h)
    original = Document.data.fget

    def bounded(d):
        assert d.name not in ("app", "hr"), "Unexpected aggregate projection"
        return original(d)

    monkeypatch.setattr(Document, "data", property(bounded, Document.data.fset))
    for path in (
        "/api/overview/summary",
        "/api/crm-registers/companies",
        "/api/crm-registers/crmQuotes",
        "/api/crm-registers/lead-options",
    ):
        assert c.get(path).status_code == 200
    comp = save(c, h, "companies", {"name": "Bounded company"})
    save(c, h, "companies", {"name": "Changed", "version": comp["version"]}, comp["id"])
    q = quote(c, h, l)
    save(c, h, "crmQuotes", {"status": "Sent", "version": q["version"]}, q["id"])
