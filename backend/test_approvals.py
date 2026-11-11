"""Enforced production approval controls; old workflow suites use explicit compatibility mode."""

from copy import deepcopy
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from werkzeug.security import generate_password_hash
from backend.test_app import app, session, PASSWORD
from backend.app import db, User, Document, Audit
from backend.erp import StockMove, JournalEntry, StockBalance
from backend.approvals import ApprovalRequest, ApprovalPolicy
from backend.test_inventory_api import make_product, product, adjust
from backend.test_trade_api import masters, purchase, create, action, details


def setup(app, limit="1000"):
    c, h = session(app)
    with app.app_context():
        db.session.add(
            User(
                id="reviewer",
                name="Independent reviewer",
                email="reviewer@example.test",
                role="Admin",
                active=True,
                password_hash=generate_password_hash(PASSWORD),
            )
        )
        db.session.add(ApprovalPolicy(id=1, limits={"Admin": limit, "Finance": limit}))
        db.session.commit()
    reviewer, rh = session(app, "reviewer")
    app.config["APPROVAL_CONTROLS_ENABLED"] = True
    return c, h, reviewer, rh


def submit(c, h, path, data, expected=202):
    r = c.post("/api" + path, headers=h, json=data)
    assert r.status_code == expected, r.json
    return r.json


def decide(
    c,
    h,
    row,
    action="approve",
    expected=200,
    reason="Reviewed supporting document and amount",
):
    return submit(
        c,
        h,
        "/approvals/requests/" + str(row["id"]) + "/" + action,
        dict(version=row["version"], reason=reason),
        expected,
    )


def inbox(c, status="Pending"):
    r = c.get("/api/approvals/requests?status=" + status)
    assert r.status_code == 200, r.json
    return r.json["items"]


def test_immediate_adjustment_requires_independent_review_and_preserves_creator(app):
    c, h = session(app)
    p = make_product(c, h)
    c, h, reviewer, rh = setup(app)
    before = product(c, p)
    payload = dict(
        productId=p,
        version=before["version"],
        quantity=2,
        unitCost=10,
        reason="Opening stock request",
        requestKey="approval-stock-one",
    )
    queued = submit(c, h, "/inventory/commands/adjust", payload)["approval"]
    assert (
        queued["assignedTo"] == "Independent reviewer" and queued["amount"] == "20.00"
    )
    assert Decimal(product(c, p)["quantity"]) == 0
    decide(c, h, queued, expected=403)
    assert len(inbox(reviewer)) == 1
    result = decide(reviewer, rh, inbox(reviewer)[0])
    assert result["approval"]["status"] == "Approved"
    assert Decimal(product(c, p)["quantity"]) == 2
    duplicate = submit(c, h, "/inventory/commands/adjust", payload)["approval"]
    assert duplicate["status"] == "Approved"
    assert Decimal(product(c, p)["quantity"]) == 2
    decide(reviewer, rh, queued, expected=409)
    with app.app_context():
        entry = db.session.scalar(
            select(JournalEntry).where(JournalEntry.source.like("stock:adjust:%"))
        )
        assert entry.created_by == "admin"
        assert db.session.scalar(select(func.count()).select_from(StockMove)) == 1
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(Audit)
                .where(Audit.action == "Approval approved")
            )
            == 1
        )


def test_missing_limits_over_limit_routing_and_policy_review(app):
    c, h = session(app)
    p = make_product(c, h)
    c, h, reviewer, rh = setup(app, limit="10")
    state = product(c, p)
    row = submit(
        c,
        h,
        "/inventory/commands/adjust",
        dict(
            productId=p,
            version=state["version"],
            quantity=2,
            unitCost=10,
            reason="Stock",
            requestKey="approval-over-limit",
        ),
    )["approval"]
    assert row["assignedTo"] is None
    decide(reviewer, rh, row, expected=403)
    policy = c.get("/api/approvals/policy").json
    submit(
        c,
        h,
        "/approvals/policy",
        dict(
            version=policy["version"],
            limits={"Admin": "100"},
            reason="Approved test authority",
        ),
        200,
    )
    ready = inbox(reviewer)[0]
    assert ready["assignedTo"] == "Independent reviewer"
    decide(reviewer, rh, ready)
    assert Decimal(product(c, p)["quantity"]) == 2
    submit(
        c,
        h,
        "/approvals/policy",
        dict(version=policy["version"], limits={"Admin": "1000"}, reason="Stale edit"),
        409,
    )
    assert c.get("/api/approvals/policy").json["limits"]["Admin"] == "100.00"


def test_pending_trade_discovery_and_rejection_reason(app):
    c, h = session(app)
    p, v, _ = masters(c, h)
    req = create(
        c,
        h,
        "requests",
        department="Operations",
        items=[dict(productId=p["id"], quantity=5, rate=10)],
    )
    req = action(c, h, "requests", req, "submit")
    c, h, reviewer, rh = setup(app)
    submit(c, h, "/approvals/refresh", {}, 200)
    row = inbox(reviewer)[0]
    assert row["amount"] == "50.00"
    decide(reviewer, rh, row, action="reject", reason="", expected=400)
    decide(reviewer, rh, row, action="reject", reason="Requested goods need revision")
    assert details(c, "requests", req["id"])["status"] == "Rejected"
    submit(c, h, "/approvals/refresh", {}, 200)
    assert inbox(reviewer) == []
    assert inbox(c, "Rejected")[0]["reason"] == "Requested goods need revision"


def test_stale_stock_rolls_back_approval_and_all_effects(app):
    c, h = session(app)
    p = make_product(c, h)
    c, h, reviewer, rh = setup(app)
    state = product(c, p)
    row = submit(
        c,
        h,
        "/inventory/commands/adjust",
        dict(
            productId=p,
            version=state["version"],
            quantity=2,
            unitCost=10,
            reason="Stock",
            requestKey="approval-stale-stock",
        ),
    )["approval"]
    # Simulate another completed stock command, then require fresh source review.
    app.config["APPROVAL_CONTROLS_ENABLED"] = False
    adjust(c, h, p, 1, 10)
    app.config["APPROVAL_CONTROLS_ENABLED"] = True
    decide(reviewer, rh, inbox(reviewer)[0], expected=409)
    assert inbox(reviewer)[0]["status"] == "Pending"
    assert Decimal(product(c, p)["quantity"]) == 1
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(StockMove)) == 1


def test_unrelated_users_limits_and_legacy_transports_cannot_bypass(app):
    c, h = session(app)
    p = make_product(c, h)
    c, h, reviewer, rh = setup(app)
    state = product(c, p)
    row = submit(
        c,
        h,
        "/inventory/commands/adjust",
        dict(
            productId=p,
            version=state["version"],
            quantity=2,
            unitCost=10,
            reason="Stock",
            requestKey="approval-private-stock",
        ),
    )["approval"]
    viewer, vh = session(app, "viewer")
    assert inbox(viewer) == []
    decide(viewer, vh, row, expected=404)
    assert viewer.get("/api/approvals/policy").status_code == 403
    assert c.post("/api/erp/stock/adjust", headers=h, json={}).status_code in (404, 410)
    assert c.patch("/api/state", headers=h, json={}).status_code == 410
    submit(
        c,
        h,
        "/inventory/commands/adjust",
        dict(
            productId=p,
            version=state["version"],
            quantity=2,
            unitCost=10,
            reason="Stock",
            lines=[dict(password="never-persist-this")],
            requestKey="approval-no-secrets",
        ),
        400,
    )
    with app.app_context():
        assert "never-persist-this" not in str(
            [(r.payload, r.review) for r in db.session.scalars(select(ApprovalRequest))]
        )


def test_payment_request_and_expense_reimbursement_are_independent(app):
    from backend.test_credit_api import setup_sale
    from backend.test_expense_api import create as expense_create, act as expense_act

    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=0)
    expense = expense_act(c, h, expense_create(c, h), "submit")
    c, h, reviewer, rh = setup(app)
    queued = submit(
        c,
        h,
        "/trade/customerPayments",
        dict(
            invoiceId=inv["id"],
            parentVersion=inv["version"],
            amount=50,
            method="Cash",
            requestKey="approval-payment-one",
        ),
    )["approval"]
    assert details(c, "customerInvoices", inv["id"])["balance"] == 330
    decide(reviewer, rh, inbox(reviewer)[0])
    assert details(c, "customerInvoices", inv["id"])["balance"] == 280
    submit(c, h, "/approvals/refresh", {}, 200)
    exp = next(r for r in inbox(reviewer) if r["module"] == "expenses")
    decide(reviewer, rh, exp)
    current = c.get("/api/expenses/claims/" + str(expense["id"])).json["record"]
    pay = submit(
        c,
        h,
        "/expenses/commands/pay",
        dict(
            id=current["id"],
            version=current["version"],
            account="1010",
            date=current["date"],
            requestKey="approval-expense-pay",
        ),
    )["approval"]
    decide(c, h, pay, expected=403)
    decide(reviewer, rh, next(r for r in inbox(reviewer) if r["id"] == pay["id"]))
    assert (
        c.get("/api/expenses/claims/" + str(expense["id"])).json["record"]["status"]
        == "Paid"
    )


def test_manufacturing_actuals_and_warehouse_transfers_are_requests(app):
    from backend.test_production_api import (
        setup as production_setup,
        order,
        action as production_action,
        detail,
    )

    c, h = session(app)
    raw, second, out, bom = production_setup(c, h)
    adjust(c, h, raw, 10, 10)
    adjust(c, h, second, 5, 3)
    mo = production_action(c, h, order(c, h, bom), "confirm")
    c, h, reviewer, rh = setup(app)
    queued = submit(
        c,
        h,
        "/production/commands/complete",
        dict(id=mo["id"], version=mo["version"], requestKey="approval-mo-complete"),
    )["approval"]
    assert detail(c, mo)["state"] == "Confirmed"
    decide(reviewer, rh, inbox(reviewer)[0])
    assert detail(c, mo)["state"] == "Done"
    state = product(c, out)
    transfer = submit(
        c,
        h,
        "/warehouse/commands/transfer",
        dict(
            productId=out,
            version=state["warehouseVersion"],
            quantity=1,
            fromLocation="Stock",
            toLocation="Returns",
            reason="Inspect manufactured output",
            requestKey="approval-transfer-output",
        ),
    )["approval"]
    assert Decimal(product(c, out)["locations"]["Returns"]) == 0
    decide(reviewer, rh, next(r for r in inbox(reviewer) if r["id"] == transfer["id"]))
    assert Decimal(product(c, out)["locations"]["Returns"]) == 1


def test_finance_journal_limits_and_source_creator(app):
    from backend.test_finance_api import command as finance

    c, h = session(app)
    draft = finance(
        c,
        h,
        "journal",
        dict(
            memo="Independent journal",
            date="2026-11-06",
            lines=[dict(account="1000", debit=25), dict(account="3000", credit=25)],
        ),
    )
    c, h, reviewer, rh = setup(app)
    row = submit(
        c,
        h,
        "/finance/commands/post",
        dict(
            id=draft["id"], version=draft["version"], requestKey="approval-journal-post"
        ),
    )["approval"]
    assert (
        c.get("/api/finance/entries/" + str(draft["id"])).json["record"]["status"]
        == "Draft"
    )
    assert row["details"]["lines"][0]["account"] == "1000"
    decide(reviewer, rh, inbox(reviewer)[0])
    assert (
        c.get("/api/finance/entries/" + str(draft["id"])).json["record"]["status"]
        == "Posted"
    )


def test_reviewer_role_revocation_and_policy_are_checked_again(app):
    c, h = session(app)
    p = make_product(c, h)
    c, h, reviewer, rh = setup(app)
    state = product(c, p)
    row = submit(
        c,
        h,
        "/inventory/commands/adjust",
        dict(
            productId=p,
            version=state["version"],
            quantity=2,
            unitCost=10,
            reason="Stock",
            requestKey="approval-revoke-role",
        ),
    )["approval"]
    with app.app_context():
        user = db.session.get(User, "reviewer")
        user.role = "Viewer"
        db.session.commit()
    assert inbox(reviewer) == []
    decide(reviewer, rh, row, expected=403)
    assert Decimal(product(c, p)["quantity"]) == 0


def test_payroll_beneficiary_cannot_approve_and_payment_requires_review(app):
    from backend.test_hr_api import employee, payroll

    c, h = session(app)
    emp = employee(c, h)
    from backend.hr_store import Employee

    with app.app_context():
        db.session.get(Employee, str(emp["id"])).linked_user_id = "manager"
        db.session.commit()
    pay = payroll(c, h, emp)
    c, h, reviewer, rh = setup(app, limit="20000")
    with app.app_context():
        doc = db.session.get(Document, "app")
        data = deepcopy(doc.data)
        for module in ("hr_payroll", "hr_employees"):
            data["roles"]["Sales Manager"]["permissions"][module] = dict(
                view=True, create=True, edit=True, approve=True, export=True
            )
        doc.data = data
        db.session.get(ApprovalPolicy, 1).limits = {
            "Admin": "20000",
            "Sales Manager": "20000",
        }
        db.session.commit()
    manager, mh = session(app, "manager")
    own = submit(
        manager,
        mh,
        "/hr/records/payroll/" + str(pay["id"]) + "/actions/approve",
        dict(version=pay["version"], requestKey="payroll-beneficiary-denied"),
    )["approval"]
    assert own["assignedTo"] == "Independent reviewer"
    decide(manager, mh, own, expected=404)
    decide(reviewer, rh, next(r for r in inbox(reviewer) if r["id"] == own["id"]))
    current = c.get("/api/hr/records/payroll/" + str(pay["id"])).json["record"]
    assert current["status"] == "Approved"
    queued = submit(
        c,
        h,
        "/hr/records/payroll/" + str(pay["id"]) + "/actions/pay",
        dict(version=current["version"], requestKey="payroll-payment-review"),
    )["approval"]
    decide(reviewer, rh, next(r for r in inbox(reviewer) if r["id"] == queued["id"]))
    assert (
        c.get("/api/hr/records/payroll/" + str(pay["id"])).json["record"]["status"]
        == "Paid"
    )


def test_credit_posting_and_refunds_require_independent_decisions(app):
    from backend.test_credit_api import setup_sale, returned, draft, step

    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=330)
    move = returned(c, h, f'deliveries:{delivery["id"]}:0', 1)
    note = step(c, h, draft(c, h, "customer", inv, move, 1), "submit")
    c, h, reviewer, rh = setup(app)
    row = submit(
        c,
        h,
        "/credits/commands/post",
        dict(id=note["id"], version=note["version"], requestKey="credit-review-post"),
    )["approval"]
    assert row["details"]["reason"] == "Returned goods"
    decide(reviewer, rh, inbox(reviewer)[0])
    current = c.get("/api/credits/" + str(note["id"])).json["record"]
    refund = submit(
        c,
        h,
        "/credits/commands/refund",
        dict(
            id=current["id"],
            version=current["version"],
            amount=33,
            account="1010",
            date=move["date"],
            requestKey="credit-review-refund",
        ),
    )["approval"]
    assert (
        c.get("/api/credits/" + str(note["id"])).json["record"]["remaining"] == "33.00"
    )
    decide(reviewer, rh, next(r for r in inbox(reviewer) if r["id"] == refund["id"]))
    assert (
        Decimal(c.get("/api/credits/" + str(note["id"])).json["record"]["remaining"])
        == 0
    )


def test_concurrent_reviewers_post_once(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    c, h = session(app)
    p = make_product(c, h)
    c, h, reviewer, rh = setup(app)
    with app.app_context():
        db.session.add(
            User(
                id="third",
                name="Third reviewer",
                email="third@example.test",
                role="Admin",
                active=True,
                password_hash=generate_password_hash(PASSWORD),
            )
        )
        db.session.commit()
    third, th = session(app, "third")
    state = product(c, p)
    row = submit(
        c,
        h,
        "/inventory/commands/adjust",
        dict(
            productId=p,
            version=state["version"],
            quantity=2,
            unitCost=10,
            reason="Stock",
            requestKey="approval-concurrent",
        ),
    )["approval"]
    clients = [(reviewer, rh), (third, th)]
    barrier = Barrier(2)

    def approve(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return client.post(
            "/api/approvals/requests/" + str(row["id"]) + "/approve",
            headers=headers,
            json=dict(version=row["version"], reason="Independent concurrent review"),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(approve, range(2)))
    assert codes == [200, 409], codes
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(StockMove)) == 1


def test_default_limits_fail_closed_and_upgrade_preserves_postings(app, monkeypatch):
    from backend.app import create_app

    monkeypatch.delenv("APPROVAL_CONTROLS_ENABLED", raising=False)
    assert (
        create_app(
            {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"}
        ).config["APPROVAL_CONTROLS_ENABLED"]
        is True
    )
    c, h = session(app)
    p = make_product(c, h)
    adjust(c, h, p, 2, 10)
    with app.app_context():
        before = db.session.scalar(select(func.count()).select_from(JournalEntry))
        ApprovalRequest.__table__.drop(db.engine)
        ApprovalPolicy.__table__.drop(db.engine)
    app.config["APPROVAL_CONTROLS_ENABLED"] = True
    submit(
        c,
        h,
        "/inventory/commands/scrap",
        dict(
            productId=p,
            quantity=1,
            version=product(c, p)["version"],
            reason="Scrap",
            requestKey="upgrade-required",
        ),
        503,
    )
    result = app.test_cli_runner().invoke(args=["migrate-storage"])
    assert result.exit_code == 0, result.output
    assert c.get("/api/approvals/policy").json["limits"] == {}
    row = submit(
        c,
        h,
        "/inventory/commands/scrap",
        dict(
            productId=p,
            quantity=1,
            version=product(c, p)["version"],
            reason="Scrap",
            requestKey="no-configured-authority",
        ),
    )["approval"]
    assert row["assignedTo"] is None
    assert Decimal(product(c, p)["quantity"]) == 2
    with app.app_context():
        assert (
            db.session.scalar(select(func.count()).select_from(JournalEntry)) == before
        )


def test_finance_inbox_uses_payment_invoice_scope_not_nonexistent_payment_id(app):
    from backend.test_credit_api import setup_sale

    c, h, p, po, bill, so, delivery, inv = setup_sale(app, pay=0)
    c, h, reviewer, rh = setup(app)
    with app.app_context():
        db.session.add(
            User(
                id="finance-reviewer",
                name="Finance approver",
                email="finance-reviewer@example.test",
                role="Finance",
                active=True,
                password_hash=generate_password_hash(PASSWORD),
            )
        )
        db.session.commit()
    finance, fh = session(app, "finance-reviewer")
    row = submit(
        c,
        h,
        "/trade/customerPayments",
        dict(
            invoiceId=inv["id"],
            parentVersion=inv["version"],
            amount=50,
            method="Cash",
            requestKey="payment-to-finance",
        ),
    )["approval"]
    assert row["assignedTo"] == "Finance approver"
    assigned = inbox(finance)
    assert [r["id"] for r in assigned] == [row["id"]]
    decide(finance, fh, assigned[0])
    assert details(c, "customerInvoices", inv["id"])["balance"] == 280


def test_direct_module_decisions_require_reason_and_cannot_rewrite_audit(app):
    c, h = session(app)
    p, v, _ = masters(c, h)
    req = action(
        c,
        h,
        "requests",
        create(
            c,
            h,
            "requests",
            department="Operations",
            items=[dict(productId=p["id"], quantity=1, rate=10)],
        ),
        "submit",
    )
    c, h, reviewer, rh = setup(app)
    pending = submit(
        reviewer,
        rh,
        "/trade/requests/" + str(req["id"]) + "/actions/approve",
        dict(version=req["version"], requestKey="direct-decision-needs-reason"),
    )["approval"]
    assert details(c, "requests", req["id"])["status"] == "Pending Approval"
    assert pending["canDecide"] is True
    decide(reviewer, rh, pending)
    req = action(
        c,
        h,
        "requests",
        create(
            c,
            h,
            "requests",
            department="Operations",
            items=[dict(productId=p["id"], quantity=1, rate=10)],
        ),
        "submit",
    )
    payload = dict(
        version=req["version"],
        requestKey="direct-reviewed-decision",
        approvalReason="Reviewed quantities and supplier justification",
    )
    result = submit(
        reviewer,
        rh,
        "/trade/requests/" + str(req["id"]) + "/actions/approve",
        payload,
        200,
    )
    assert result["record"]["status"] == "Approved"
    submit(
        reviewer,
        rh,
        "/trade/requests/" + str(req["id"]) + "/actions/approve",
        {**payload, "approvalReason": "Attempted audit rewrite"},
        202,
    )
    with app.app_context():
        row = db.session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.request_key == "direct-reviewed-decision"
            )
        )
        assert row.reason == "Reviewed quantities and supplier justification"


def test_department_manager_limit_escalates_to_finance_without_granting_payment_rights(
    app,
):
    from backend.test_expense_api import cmd as expense_cmd, act as expense_act

    with app.app_context():
        state = db.session.get(Document, "app")
        data = deepcopy(state.stored_data)
        data["roles"]["Sales Manager"]["permissions"]["expenses"]["approve"] = True
        state.data = data
        db.session.add(
            User(
                id="finance",
                name="Finance",
                email="finance@example.test",
                role="Finance",
                active=True,
                password_hash=generate_password_hash(PASSWORD),
            )
        )
        db.session.add(
            ApprovalPolicy(
                id=1, limits={"Sales Manager": "100.00", "Finance": "1000.00"}
            )
        )
        db.session.commit()
    app.config["APPROVAL_CONTROLS_ENABLED"] = True
    seller, sh = session(app, "seller")
    manager, mh = session(app, "manager")
    finance, fh = session(app, "finance")
    for amount, reviewer, headers, assigned in (
        (50, manager, mh, "manager"),
        (250, finance, fh, "Finance"),
    ):
        row = expense_cmd(
            seller,
            sh,
            "create",
            amount=amount,
            tax=0,
            description="Manager and Finance authority acceptance",
        )
        row = expense_act(seller, sh, row, "submit")
        queued = submit(
            seller,
            sh,
            "/expenses/commands/approve",
            {
                "id": row["id"],
                "version": row["version"],
                "requestKey": "acceptance-review-" + str(amount),
            },
        )["approval"]
        assert queued["assignedTo"] == assigned
        decide(seller, sh, queued, expected=404)
        decide(reviewer, headers, queued)
        current = seller.get("/api/expenses/claims/" + str(row["id"])).json["record"]
        assert current["status"] == "Approved"
        payment = submit(
            seller,
            sh,
            "/expenses/commands/pay",
            {
                "id": current["id"],
                "version": current["version"],
                "account": "1010",
                "date": current["date"],
                "requestKey": "acceptance-pay-" + str(amount),
            },
        )["approval"]
        assert payment["assignedTo"] == "Finance"
        decide(manager, mh, payment, expected=404)
        decide(finance, fh, payment)
        assert (
            seller.get("/api/expenses/claims/" + str(row["id"])).json["record"][
                "status"
            ]
            == "Paid"
        )
