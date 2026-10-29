"""Native expense privacy, state transitions, receipts and financial simulations."""

import io
from decimal import Decimal
from sqlalchemy import select, func
from backend.test_app import app, session
from backend.app import db, Document
from backend.erp import Expense, JournalEntry, JournalLine

counter = 0


def cmd(c, h, kind, expected=200, **data):
    global counter
    counter += 1
    r = c.post(
        "/api/expenses/commands/" + kind,
        headers=h,
        json={"requestKey": "expense-test-" + str(counter), **data},
    )
    assert r.status_code == expected, r.json
    return r.json.get("record")


def create(c, h, **extra):
    return cmd(
        c,
        h,
        "create",
        description="Demo client visit",
        amount="100",
        tax="10",
        date="2026-10-28",
        **extra,
    )


def act(c, h, e, a, expected=200, **extra):
    return cmd(c, h, a, expected, id=e["id"], version=e["version"], **extra)


def get(c, e):
    return c.get("/api/expenses/claims/" + str(e["id"])).json["record"]


def test_expense_lifecycle_receipt_and_ledger(app):
    c, h = session(app)
    upload = c.post(
        "/api/attachments",
        headers=h,
        data={
            "module": "expenses",
            "file": (io.BytesIO(b"%PDF-1.4 demo"), "receipt.pdf"),
        },
    ).json
    e = create(c, h, attachmentId=upload["attachmentPath"])
    assert e["employee"] == "admin" and e["status"] == "Draft"
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 0
    for action in ("submit", "approve"):
        e = act(c, h, e, action)
    data = dict(
        id=e["id"],
        version=e["version"],
        requestKey="expense-payment-replay",
        account="1000",
        date="2026-10-28",
    )
    e = cmd(c, h, "pay", **data)
    assert e["status"] == "Paid" and e["actions"] == []
    assert cmd(c, h, "pay", **data)["id"] == e["id"]
    with app.app_context():
        entries = db.session.scalars(
            select(JournalEntry).order_by(JournalEntry.id)
        ).all()
        assert len(entries) == 2
        assert [x.source for x in entries] == [
            f"expense:{e['id']}",
            f"expense:{e['id']}:payment",
        ]
        assert all(sum(l.debit - l.credit for l in x.lines) == 0 for x in entries)
        for code, expected in [
            ("6105", 100),
            ("1300", 10),
            ("2350", 0),
            ("1000", -110),
        ]:
            assert (
                db.session.scalar(
                    select(
                        func.coalesce(
                            func.sum(JournalLine.debit - JournalLine.credit), 0
                        )
                    ).where(JournalLine.account == code)
                )
                == expected
            )
        entry_id = entries[0].id
    assert Decimal(c.get("/api/finance/summary").json["balanceCheck"]) == 0
    assert c.get("/api/expenses/claims/" + str(e["id"]) + "/print").status_code == 200
    assert c.get("/api/attachments/" + e["attachmentId"]).status_code == 200
    assert (
        c.get("/api/finance/entries/" + str(entry_id))
        .json["record"]["sourceLink"]["href"]
        .endswith("/print")
    )


def test_expense_sql_scope_owner_manager_finance(app):
    owner, h = session(app, "seller")
    manager, mh = session(app, "manager")
    other, oh = session(app, "hr")
    admin, ah = session(app)
    a = create(owner, h)
    b = create(other, oh)
    assert owner.get("/api/expenses/claims").json["total"] == 1
    assert manager.get("/api/expenses/claims").json["items"][0]["id"] == a["id"]
    assert manager.get("/api/expenses/summary").json["states"] == {"Draft": 1}
    assert other.get("/api/expenses/claims/" + str(a["id"])).status_code == 404
    assert (
        other.get("/api/expenses/claims/" + str(a["id"]) + "/print").status_code == 404
    )
    act(manager, mh, a, "submit", 403)
    act(owner, h, a, "approve", 403)
    assert admin.get("/api/expenses/claims").json["total"] == 2
    with app.app_context():
        from backend.app import User

        db.session.get(User, "hr").role = "Finance"
        db.session.commit()
    assert other.get("/api/expenses/claims").json["total"] == 2
    a = act(owner, h, a, "submit")
    a = act(other, oh, get(other, a), "approve")
    a = act(other, oh, a, "pay")
    assert a["status"] == "Paid"


def test_expense_versions_replay_permissions_validation(app):
    c, h = session(app)
    e = create(c, h)
    cmd(c, h, "submit", 428, id=e["id"])
    old = e
    e = act(c, h, e, "submit")
    act(c, h, old, "approve", 409)
    e = act(c, h, e, "reject")
    assert e["status"] == "Rejected"
    act(c, h, e, "submit", 403)
    for extra in [
        {"amount": 0},
        {"tax": 101},
        {"tax": -1},
        {"account": "1000"},
        {"ownerId": "seller"},
        {"employee": "Other"},
        {"description": ""},
        {"date": "bad"},
    ]:
        data = dict(description="Invalid", amount=100, tax=0, date="2026-10-28")
        data.update(extra)
        cmd(c, h, "create", 400, **data)
    body = dict(description="Idempotent", amount=1, requestKey="expense-collision-key")
    one = cmd(c, h, "create", **body)
    assert cmd(c, h, "create", **body)["id"] == one["id"]
    cmd(c, h, "create", 409, **{**body, "amount": 2})
    viewer, vh = session(app, "viewer")
    cmd(viewer, vh, "create", 403, description="No", amount=1)
    with app.app_context():
        doc = db.session.get(Document, "app")
        s = dict(doc.stored_data)
        import copy

        s = copy.deepcopy(s)
        s["roles"]["Viewer"]["permissions"]["expenses"]["view"] = False
        doc.stored_data = s
        db.session.commit()
    assert viewer.get("/api/expenses/claims").status_code == 403


def test_expense_attachment_scope_paging_and_print_escape(app):
    c, h = session(app)
    seller, sh = session(app, "seller")
    upload = seller.post(
        "/api/attachments",
        headers=sh,
        data={"module": "expenses", "file": (io.BytesIO(b"%PDF-1.4"), "other.pdf")},
    ).json
    cmd(
        c,
        h,
        "create",
        403,
        description="Foreign receipt",
        amount=1,
        attachmentId=upload["attachmentPath"],
    )
    e = cmd(c, h, "create", description="<script>alert(1)</script>", amount=1)
    assert (
        b"&lt;script&gt;"
        in c.get("/api/expenses/claims/" + str(e["id"]) + "/print").data
    )
    for i in range(27):
        cmd(c, h, "create", description="Paged " + str(i), amount=1)
    r = c.get("/api/expenses/claims?page=2&pageSize=25").json
    assert r["total"] == 28 and len(r["items"]) == 3
    assert c.get("/api/expenses/claims?search=Paged%202").json["total"] == 8
    for query in ["page=0", "status=Invalid", "from=2026-10-29&to=2026-10-28"]:
        assert c.get("/api/expenses/claims?" + query).status_code == 400
    assert c.get("/api/expenses/accounts?pageSize=100").json["total"] >= 4


def test_expense_period_lock_atomicity_and_no_aggregate(app, monkeypatch):
    c, h = session(app)
    e = create(c, h)
    e = act(c, h, e, "submit")
    from backend.erp import ERPControl

    with app.app_context():
        db.session.get(ERPControl, 1).lock_date = "2026-10-28"
        db.session.commit()
    act(c, h, e, "approve", 400)
    assert get(c, e)["status"] == "Submitted"
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 0
        db.session.get(ERPControl, 1).lock_date = None
        db.session.commit()
    original = Document.data.fget

    def bounded(doc):
        assert doc.name not in ("app", "hr"), "Aggregate projection read"
        return original(doc)

    monkeypatch.setattr(Document, "data", property(bounded, Document.data.fset))
    assert c.get("/api/expenses/claims").status_code == 200
    assert c.get("/api/expenses/summary").status_code == 200
    e = act(c, h, e, "approve")
    with app.app_context():
        db.session.get(ERPControl, 1).lock_date = "2026-10-28"
        db.session.commit()
    act(c, h, e, "pay", 400, date="2026-10-28")
    assert get(c, e)["status"] == "Approved"
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 1
        db.session.get(ERPControl, 1).lock_date = None
        db.session.commit()
    e = act(c, h, e, "pay")
    assert e["status"] == "Paid"
    upload = c.post(
        "/api/attachments",
        headers=h,
        data={"module": "expenses", "file": (io.BytesIO(b"%PDF-1.4"), "bounded.pdf")},
    ).json
    assert c.get("/api/attachments/" + upload["attachmentPath"]).status_code == 200
