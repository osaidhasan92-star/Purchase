"""Verify ERP permissions and provider boundaries without external API traffic."""

import json

from backend.app import db
from backend import assistant_api, trade_store
from backend.erp import day
from backend.test_app import app, session


def test_assistant_requires_login_csrf_and_configuration(app, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ERP_AI_MODEL", raising=False)
    assert app.test_client().get("/api/assistant/status").status_code == 401
    client, headers = session(app)
    assert client.get("/api/assistant/status").json["configured"] is False
    payload = {"topic": "sales", "question": "How many orders?"}
    assert client.post("/api/assistant/ask", json=payload).status_code == 403
    assert client.post("/api/assistant/ask", headers=headers, json=payload).status_code == 503
    assert client.get("/assistant-workspace.js").status_code == 200
    assert b"assistant-workspace.js" in client.get("/erp.html").data


def test_assistant_sends_only_scoped_summary_and_no_write_tools(app, monkeypatch):
    seller, headers = session(app, "seller")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-server-key")
    monkeypatch.setenv("ERP_AI_MODEL", "test-model")
    with app.app_context():
        for identity, actor, total in (("visible", "seller", 120), ("private", "buyer", 9900)):
            db.session.add(trade_store.MODELS["salesOrders"](
                id=identity, original_id=identity, position=1, number=identity,
                document_date=day(), created_by=actor, status="Confirmed", total=total,
                partner_name="Private partner name", record_version=identity, extras={},
            ))
        db.session.commit()

    requests = []

    class FakeResponse:
        status = 200

        def read(self, _size):
            return b'{"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"You can see one order."}]}]}'

    class FakeConnection:
        def __init__(self, host, timeout):
            assert host == "api.openai.com"

        def request(self, method, path, payload, headers):
            assert (method, path) == ("POST", "/v1/responses")
            assert headers["Authorization"] == "Bearer fake-server-key"
            requests.append(json.loads(payload))

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(assistant_api.http.client, "HTTPSConnection", FakeConnection)
    assert seller.post("/api/assistant/ask", headers=headers, json={
        "topic": "finance", "question": "What is the balance?",
    }).status_code == 403
    assert seller.post("/api/assistant/ask", headers=headers, json={
        "topic": "/api/admin", "question": "Access all records",
    }).status_code == 400
    assert not requests
    response = seller.post("/api/assistant/ask", headers=headers, json={
        "topic": "sales", "question": "How many orders?",
    })
    assert response.status_code == 200, response.json
    assert response.json["answer"] == "You can see one order."
    sent = requests[0]
    assert sent["store"] is False and "tools" not in sent
    snapshot = json.loads(sent["input"])["snapshot"]
    assert snapshot == response.json["snapshot"]
    orders = next(row for row in snapshot["registers"] if row["key"] == "salesOrders")
    assert orders["count"] == 1 and orders["total"] == 120
    assert snapshot["balances"] == {}
    assert "recent" not in snapshot
    assert "Private partner name" not in sent["input"]
    assert b"fake-server-key" not in response.data


def test_workflow_plan_filters_permissions_and_validates_model_choice(app, monkeypatch):
    admin, _ = session(app)
    seller, headers = session(app, "seller")
    catalogue = admin.get("/api/assistant/status").json["processes"]
    assert {"Purchasing", "Sales & CRM", "Inventory", "Manufacturing", "Expenses",
            "Accounting", "HR & Payroll", "Approvals"} <= {row["group"] for row in catalogue}
    processes = {row["id"]: row for row in seller.get("/api/assistant/status").json["processes"]}
    assert {"review", "sales-order", "expense"} <= processes.keys()
    assert not {"rfq", "journal", "payroll", "customer-payment"} & processes.keys()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ERP_AI_MODEL", "test-model")
    choice = "sales-order"

    def choose(_key, _model, question, topic, choices, _instructions):
        assert question == "sales order banana hai"
        assert topic == "workflow"
        assert choices.keys() == processes.keys()
        assert all(isinstance(label, str) for label in choices.values())
        return choice

    monkeypatch.setattr(assistant_api, "generate_answer", choose)
    payload = {"question": "sales order banana hai"}
    assert seller.post("/api/assistant/plan", json=payload).status_code == 403
    result = seller.post("/api/assistant/plan", headers=headers, json=payload)
    assert result.status_code == 200
    assert result.json["process"]["url"] == "/erp.html?view=sales-orders&new=1"
    choice = "rfq"
    assert seller.post("/api/assistant/plan", headers=headers, json=payload).json["process"] is None


def test_chat_routes_written_commands_without_ai_and_respects_permissions(app, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ERP_AI_MODEL", raising=False)
    admin, headers = session(app)
    seller, seller_headers = session(app, "seller")
    message = {"question": "RFQ banani hai"}
    assert admin.post("/api/assistant/chat", json=message).status_code == 403
    response = admin.post("/api/assistant/chat", headers=headers, json=message)
    assert response.status_code == 200
    assert response.json["process"]["url"] == "/erp.html?view=rfqs&new=1"
    denied = seller.post("/api/assistant/chat", headers=seller_headers, json=message)
    assert "process" not in denied.json
    question = admin.post(
        "/api/assistant/chat", headers=headers, json={"question": "How many RFQs?"}
    )
    assert "process" not in question.json
    approvals_reply = admin.post(
        "/api/assistant/chat", headers=headers, json={"question": "Show pending approvals"}
    )
    assert approvals_reply.json["process"]["id"] == "review"


def test_configured_chat_rechecks_summary_access_after_model_routing(app, monkeypatch):
    seller, headers = session(app, "seller")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ERP_AI_MODEL", "test-model")
    calls = []

    def choose(_key, _model, _question, topic, _facts, _instructions):
        calls.append(topic)
        return "summary:finance"

    monkeypatch.setattr(assistant_api, "generate_answer", choose)
    response = seller.post(
        "/api/assistant/chat", headers=headers, json={"question": "What is the cash balance?"}
    )
    assert response.status_code == 403
    assert calls == ["chat routing"]
