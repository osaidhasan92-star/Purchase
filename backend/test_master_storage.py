"""Migration round trips, SQL-backed APIs and compatibility posting behavior."""

from copy import deepcopy
from sqlalchemy import select, event
from backend.test_app import app, session, patch
from backend.app import db, Document, create_app
from backend.master_store import Customer, Vendor, Product, MARKER
from backend.erp import ERPProduct, StockBalance


def test_existing_database_migration_is_idempotent_and_preserves_records(app):
    client, h = session(app)
    rows = {
        "customers": [
            dict(
                id=31,
                name="Existing customer",
                code="CUS-2026-007",
                creditLimit=12.5,
                customNote={"retain": True},
            )
        ],
        "vendors": [
            dict(id="v-legacy", name="Supplier", trn="NTN-123", customField="keep")
        ],
        "products": [
            dict(
                id=42,
                name="Stock product",
                unit="Each",
                rate=1.25,
                sku="OLD",
                productType="stock",
            )
        ],
    }
    with app.app_context():
        doc = db.session.get(Document, "app")
        old = deepcopy(doc.data)
        old.update(rows)
        # Simulate the actual old on-disk format, bypassing the modern adapter.
        doc.stored_data = old
        db.session.query(Customer).delete()
        db.session.query(Vendor).delete()
        db.session.query(Product).delete()
        db.session.commit()
    assert client.get("/api/customers").status_code == 503
    runner = app.test_cli_runner()
    first = runner.invoke(args=["migrate-storage"])
    assert first.exit_code == 0, first.output
    with app.app_context():
        doc = db.session.get(Document, "app")
        revision = doc.revision
        assert doc.stored_data[MARKER] == 1
        assert all(key not in doc.stored_data for key in rows)
        assert all(doc.data[key] == values for key, values in rows.items())
        assert db.session.get(Customer, "31").name == "Existing customer"
    again = runner.invoke(args=["migrate-storage"])
    assert again.exit_code == 0, again.output
    with app.app_context():
        assert db.session.get(Document, "app").revision == revision
    other = create_app(
        {
            "TESTING": True,
            "COOKIE_SECURE": False,
            "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"],
        }
    )
    reader, _ = session(other)
    assert reader.get("/api/products").json["items"][0]["sku"] == "OLD"
    assert reader.get("/api/state").json["state"]["vendors"] == rows["vendors"]


def test_native_masters_use_individual_sql_writes_and_reject_stale_edits(app):
    client, h = session(app)
    responses = []
    for resource, fields in [
        (
            "vendors",
            dict(name="Native supplier", trn="1234567", email="supplier@example.test"),
        ),
        (
            "products",
            dict(
                name="Native product",
                sku="SQL-01",
                unit="Box",
                rate=12.25,
                productType="stock",
            ),
        ),
    ]:
        before = client.get("/api/state").json["revision"]
        payload = {**fields, "requestKey": resource + "-request-001"}
        response = client.post("/api/" + resource, headers=h, json=payload)
        assert response.status_code == 200, response.json
        value = response.json["record"]
        responses.append((resource, value))
        assert response.json["revision"] == before + 1
        assert (
            client.post("/api/" + resource, headers=h, json=payload).json["record"][
                "id"
            ]
            == value["id"]
        )
        assert (
            client.post(
                "/api/" + resource, headers=h, json={**payload, "name": "Different"}
            ).status_code
            == 409
        )
        edited = client.patch(
            "/api/" + resource + "/" + str(value["id"]),
            headers=h,
            json={"version": value["version"], "category": "Updated category"},
        )
        assert edited.status_code == 200, edited.json
        assert edited.json["record"]["name"] == fields["name"]
        assert (
            client.patch(
                "/api/" + resource + "/" + str(value["id"]),
                headers=h,
                json={"version": value["version"], "name": "Stale"},
            ).status_code
            == 409
        )
        assert (
            client.patch(
                "/api/" + resource + "/" + str(value["id"]),
                headers=h,
                json={"name": "No version"},
            ).status_code
            == 428
        )
        assert (
            client.get("/api/" + resource + "?search=updated%20category").json["total"]
            == 1
        )
    with app.app_context():
        product = db.session.get(ERPProduct, str(responses[1][1]["id"]))
        assert product.kind == "stock" and product.unit == "Box"
        assert db.session.get(StockBalance, product.id).quantity == 0
        assert "products" not in db.session.get(Document, "app").stored_data
    viewer, vh = session(app, "viewer")
    for resource, value in responses:
        assert viewer.get("/api/" + resource).status_code == 200
        assert (
            viewer.post(
                "/api/" + resource,
                headers=vh,
                json={"name": "Blocked", "requestKey": "blocked-key-123"},
            ).status_code
            == 403
        )
        assert (
            viewer.patch(
                "/api/" + resource + "/" + str(value["id"]),
                headers=vh,
                json={"version": value["version"], "name": "Blocked"},
            ).status_code
            == 403
        )


def test_sql_pagination_literal_search_and_no_collection_materialization(app):
    client, h = session(app)
    assert (
        patch(
            client,
            h,
            {
                "vendors": [
                    dict(id=i, name=f"Supplier {i:03}", category="General")
                    for i in range(140)
                ]
                + [dict(id=999, name="Literal %_ supplier")]
            },
        ).status_code
        == 200
    )
    statements = []
    with app.app_context():
        engine = db.engine

        def capture(conn, cursor, statement, parameters, context, executemany):
            if "master_vendor" in statement:
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/vendors?page=3&pageSize=25")
        assert (
            response.status_code == 200
            and len(response.json["items"]) == 25
            and response.json["total"] == 141
        )
        # The API must not read all rows just to render one page.
        assert len(statements) == 2 and any("LIMIT" in s for s in statements)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert client.get("/api/vendors?search=%25_").json["total"] == 1
    assert client.get("/api/vendors?pageSize=101").status_code == 400
    assert client.get("/api/vendors?page=-1").status_code == 400
    assert client.get("/api/vendors?page=bad").status_code == 400
    assert client.get("/api/products?search=" + ("a" * 161)).status_code == 400


def test_legacy_and_native_master_writes_share_one_canonical_record(app):
    client, h = session(app)
    created = client.post(
        "/api/products",
        headers=h,
        json={
            "name": "Shared",
            "unit": "Each",
            "rate": 5,
            "requestKey": "shared-product-key",
        },
    ).json["record"]
    snapshot = client.get("/api/state").json
    change = client.patch(
        "/api/products/" + str(created["id"]),
        headers=h,
        json={"version": created["version"], "rate": 6},
    )
    assert change.status_code == 200
    assert (
        patch(
            client,
            h,
            {"products": snapshot["state"]["products"]},
            revision=snapshot["revision"],
        ).status_code
        == 409
    )
    latest = client.get("/api/state").json["state"]["products"]
    latest[0]["rate"] = 7
    assert patch(client, h, {"products": latest}).status_code == 200
    assert client.get("/api/products").json["items"][0]["rate"] == 7
    assert (
        client.patch(
            "/api/products/" + str(created["id"]),
            headers=h,
            json={"version": change.json["record"]["version"], "rate": 8},
        ).status_code
        == 409
    )
    with app.app_context():
        assert db.session.scalar(select(Product)).rate == 7


def test_native_master_validation_and_atomic_rollback(app):
    client, h = session(app)
    assert (
        client.post(
            "/api/vendors",
            headers=h,
            json={"name": "A", "createdBy": "viewer", "requestKey": "forged-owner-key"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/vendors",
            headers=h,
            json={"name": "A", "email": "invalid", "requestKey": "bad-email-key"},
        ).status_code
        == 400
    )
    for rate in (-1, True, "10"):
        assert (
            client.post(
                "/api/products",
                headers=h,
                json={
                    "name": "Invalid",
                    "rate": rate,
                    "requestKey": "invalid-rate-key",
                },
            ).status_code
            == 400
        )
    assert (
        client.post(
            "/api/products",
            headers=h,
            json={
                "name": "Invalid",
                "productType": "wrong",
                "requestKey": "invalid-kind-key",
            },
        ).status_code
        == 400
    )
    assert client.get("/api/products").json["total"] == 0


def test_native_product_type_cannot_change_after_stock_history(app):
    client, h = session(app)
    product = client.post(
        "/api/products",
        headers=h,
        json={
            "name": "History product",
            "productType": "stock",
            "unit": "Each",
            "rate": 5,
            "requestKey": "history-product-key",
        },
    ).json["record"]
    adjusted = client.post(
        "/api/erp/inventory/adjust",
        headers=h,
        json={
            "productId": product["id"],
            "quantity": 2,
            "unitCost": 5,
            "reason": "Opening stock",
            "requestKey": "history-adjustment-key",
        },
    )
    assert adjusted.status_code == 200, adjusted.json
    response = client.patch(
        "/api/products/" + str(product["id"]),
        headers=h,
        json={"version": product["version"], "productType": "service"},
    )
    assert response.status_code == 400, response.json
    assert client.get("/api/products").json["items"][0]["productType"] == "stock"
    with app.app_context():
        assert db.session.get(ERPProduct, str(product["id"])).kind == "stock"
        assert db.session.get(StockBalance, str(product["id"])).quantity == 2


def test_migration_rolls_back_if_legacy_values_cannot_round_trip(app):
    with app.app_context():
        doc = db.session.get(Document, "app")
        original = deepcopy(doc.data)
        original["products"] = [
            dict(id=44, name="Too precise legacy rate", rate=1.23456789)
        ]
        doc.stored_data = original
        db.session.commit()
    result = app.test_cli_runner().invoke(args=["migrate-storage"])
    assert result.exit_code != 0 and "could not round-trip exactly" in result.output
    with app.app_context():
        doc = db.session.get(Document, "app")
        assert not doc.stored_data.get(MARKER)
        assert doc.stored_data["products"][0]["rate"] == 1.23456789
        assert db.session.get(Product, "44") is None
