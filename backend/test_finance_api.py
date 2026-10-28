"""Independent ledger, permission and native finance command simulations."""

from copy import deepcopy
from decimal import Decimal
import pytest
from sqlalchemy import select, func, event
from backend.test_app import app, session, PASSWORD
from backend.app import db, Document, User
from backend.erp import JournalEntry, JournalLine, Reconciliation, BankStatementLine
from werkzeug.security import generate_password_hash

counter = 0


def command(c, h, name, data, expected=200):
    global counter
    counter += 1
    r = c.post(
        "/api/finance/commands/" + name,
        headers=h,
        json={"requestKey": "finance-test-" + str(counter), **data},
    )
    assert r.status_code == expected, r.json
    return r.json.get("record")


def journal(
    c,
    h,
    amount=100,
    debit="1010",
    credit="3000",
    memo="Native journal",
    date="2026-10-01",
    partner="",
):
    return command(
        c,
        h,
        "journal",
        dict(
            memo=memo,
            date=date,
            lines=[
                dict(account=debit, debit=amount, partner=partner),
                dict(account=credit, credit=amount, partner=partner),
            ],
        ),
    )


def post(c, h, j):
    return command(c, h, "post", dict(id=j["id"], version=j["version"]))


def details(c, j):
    return c.get("/api/finance/entries/" + str(j["id"])).json["record"]


def finance_user(app, uid="finance", permissions=None):
    with app.app_context():
        db.session.add(
            User(
                id=uid,
                name=uid,
                email=uid + "@example.test",
                role="Finance",
                active=True,
                password_hash=generate_password_hash(PASSWORD),
            )
        )
        if permissions:
            doc = db.session.get(Document, "app")
            s = deepcopy(doc.data)
            s["roles"]["Finance"]["permissions"]["accounting"] = permissions
            doc.data = s
        db.session.commit()
    return session(app, uid)


def test_manual_draft_edit_post_reverse_and_print(app):
    c, h = session(app)
    j = journal(c, h, memo="<script>demo</script>")
    assert j["status"] == "Draft"
    assert Decimal(c.get("/api/finance/summary").json["cashBank"]) == 0
    j = command(
        c,
        h,
        "edit-journal",
        dict(
            id=j["id"],
            version=j["version"],
            memo="<script>edited</script>",
            date="2026-10-02",
            lines=[
                dict(account="1010", debit="125.25"),
                dict(account="3000", credit="125.25"),
            ],
        ),
    )
    j = post(c, h, j)
    assert j["status"] == "Posted"
    assert "edit" not in j["actions"]
    report = c.get("/api/finance/summary").json
    assert Decimal(report["cashBank"]) == Decimal("125.25")
    assert Decimal(report["balanceCheck"]) == 0
    command(
        c,
        h,
        "edit-journal",
        dict(
            id=j["id"],
            version=j["version"],
            memo="Bad",
            date="2026-10-02",
            lines=[dict(account="1010", debit=1), dict(account="3000", credit=1)],
        ),
        409,
    )
    html = c.get("/api/finance/entries/" + str(j["id"]) + "/print").text
    assert (
        "&lt;script&gt;edited&lt;/script&gt;" in html and "<script>edited" not in html
    )
    rev = command(
        c, h, "reverse", dict(id=j["id"], version=j["version"], date="2026-10-03")
    )
    assert rev["reversalOf"] == j["id"]
    assert "reverse" not in details(c, j)["actions"]
    assert Decimal(c.get("/api/finance/summary").json["cashBank"]) == 0
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 2
        for e in db.session.scalars(select(JournalEntry)):
            assert sum(l.debit for l in e.lines) == sum(l.credit for l in e.lines)


def test_validation_balances_fields_dates_and_ranges(app):
    c, h = session(app)
    base = dict(
        memo="Invalid",
        date="2026-10-01",
        lines=[dict(account="1010", debit=100), dict(account="3000", credit=99)],
    )
    command(c, h, "journal", base, 400)
    for bad in (True, -1, "NaN", "Infinity", "1000000000001"):
        command(
            c,
            h,
            "journal",
            {
                **base,
                "lines": [
                    dict(account="1010", debit=bad),
                    dict(account="3000", credit=bad),
                ],
            },
            400,
        )
    command(c, h, "journal", {**base, "date": False}, 400)
    command(c, h, "journal", {**base, "status": "Posted"}, 400)
    command(
        c,
        h,
        "journal",
        {
            **base,
            "lines": [
                dict(account="1010", debit=100, credit=100),
                dict(account="3000", credit=100),
            ],
        },
        400,
    )
    command(c, h, "account", dict(code="12", name="Bad", type="asset"), 400)
    command(
        c,
        h,
        "account",
        dict(code="1999", name="Bad", type="asset", reconcile="true"),
        400,
    )
    assert (
        c.get("/api/finance/reports?from=2026-11-01&to=2026-10-01").status_code == 400
    )
    assert c.get("/api/finance/entries?pageSize=101").status_code == 400


def test_retries_keys_conflicts_actor_scoping_and_versions(app):
    c, h = session(app)
    data = dict(
        requestKey="journal-key-repeat",
        memo="Idempotent",
        date="2026-10-01",
        lines=[dict(account="1000", debit=50), dict(account="3000", credit=50)],
    )
    a = command(c, h, "journal", data)
    b = command(c, h, "journal", data)
    assert a["id"] == b["id"]
    command(c, h, "journal", {**data, "memo": "Different"}, 409)
    command(c, h, "post", dict(id=a["id"]), 428)
    a = post(c, h, a)
    command(c, h, "post", dict(id=a["id"], version=b["version"]), 409)
    f, fh = finance_user(app)
    other = command(f, fh, "journal", data)
    assert other["id"] != a["id"]
    transfer = dict(
        requestKey="transfer-retry-key",
        fromAccount="1010",
        toAccount="1000",
        amount=20,
        date="2026-10-01",
    )
    t = command(c, h, "transfer", transfer)
    assert command(c, h, "transfer", transfer)["id"] == t["id"]
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 3


def test_scopes_company_finance_readonly_and_create_without_approve(app):
    c, h = session(app)
    j = post(c, h, journal(c, h))
    v, vh = session(app, "viewer")
    for path in (
        "summary",
        "accounts",
        "entries",
        "reports",
        "ledger",
        "open-items",
        "statements",
        "period-lock",
    ):
        assert v.get("/api/finance/" + path).status_code == 403
    assert v.get("/api/finance/entries/" + str(j["id"]) + "/print").status_code == 403
    f, fh = finance_user(
        app,
        permissions=dict(
            view=True, create=True, edit=False, approve=False, export=False
        ),
    )
    assert f.get("/api/finance/entries/" + str(j["id"])).status_code == 200
    assert f.get("/api/finance/ledger/export").status_code == 403
    command(
        f, fh, "transfer", dict(fromAccount="1010", toAccount="1000", amount=10), 403
    )
    own = journal(f, fh)
    command(f, fh, "post", dict(id=own["id"], version=own["version"]), 403)
    assert f.get("/api/finance/summary").json["periodLock"]["date"] is None
    command(f, fh, "period-lock", dict(date="2026-01-01"), 403)


def test_sql_report_opening_period_and_cumulative_equations(app):
    c, h = session(app)
    post(c, h, journal(c, h, 1000, date="2026-09-01"))
    post(c, h, journal(c, h, 200, debit="1010", credit="4100", date="2026-10-02"))
    post(c, h, journal(c, h, 30, debit="6105", credit="1010", date="2026-10-03"))
    journal(c, h, 9999, memo="Unposted excluded")
    query = "?from=2026-10-01&to=2026-10-31"
    s = c.get("/api/finance/summary" + query).json
    expected = dict(
        cashBank=1170,
        assets=1170,
        liabilities=0,
        equity=1000,
        currentEarnings=170,
        profit=170,
        openingCash=1000,
        cashIn=200,
        cashOut=30,
        closingCash=1170,
        balanceCheck=0,
        periodDebit=230,
        periodCredit=230,
    )
    for k, v in expected.items():
        assert Decimal(s[k]) == v, (k, s)
    r = c.get("/api/finance/reports" + query + "&search=Main%20Bank").json
    assert r["total"] == 1
    assert Decimal(r["items"][0]["opening"]) == 1000
    assert Decimal(r["summary"]["profit"]) == 170
    assert c.get("/api/finance/ledger" + query).json["total"] == 4
    assert c.get("/api/finance/reports" + query + "&kind=pnl").json["total"] >= 2


def test_sql_bounded_headers_and_no_aggregate_projection(app, monkeypatch):
    c, h = session(app)
    for i in range(3):
        post(c, h, journal(c, h, i + 1, memo="Paged " + str(i)))
    original = Document.data

    def blocked(self):
        raise AssertionError(
            "Native finance reads must not materialize aggregate state"
        )

    monkeypatch.setattr(Document, "data", property(blocked, original.fset))
    with app.app_context():
        statements = []

        def trace(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", trace)
        try:
            response = c.get("/api/finance/entries?pageSize=1&page=2")
            assert response.status_code == 200, response.json
            assert (
                response.json["total"] == 3
                and len(response.json["items"]) == 1
                and "lines" not in response.json["items"][0]
            )
            assert not any("SELECT journal_line.id" in s for s in statements)
            assert c.get("/api/finance/summary").status_code == 200
            assert c.get("/api/finance/reports").status_code == 200
        finally:
            event.remove(db.engine, "before_cursor_execute", trace)


def test_partial_reconcile_stale_versions_retry_and_partner_checks(app):
    c, h = session(app)
    invoice = post(
        c, h, journal(c, h, 100, debit="1100", credit="4100", partner="customer:one")
    )
    payment = post(
        c, h, journal(c, h, 60, debit="1010", credit="1100", partner="customer:one")
    )
    a = next(l for l in invoice["lines"] if l["account"] == "1100")
    b = next(l for l in payment["lines"] if l["account"] == "1100")
    payload = dict(
        requestKey="partial-match-repeat",
        debitLine=a["id"],
        creditLine=b["id"],
        debitVersion=a["version"],
        creditVersion=b["version"],
        amount=40,
    )
    result = command(c, h, "reconcile", payload)
    assert Decimal(result["openAmount"]) == 60
    command(c, h, "reconcile", payload)
    command(
        c,
        h,
        "reconcile",
        {**payload, "requestKey": "match-stale-version", "amount": 10},
        409,
    )
    a = c.get("/api/finance/lines/" + str(a["id"])).json["record"]
    b = c.get("/api/finance/lines/" + str(b["id"])).json["record"]
    command(
        c,
        h,
        "reconcile",
        dict(
            debitLine=a["id"],
            creditLine=b["id"],
            debitVersion=a["version"],
            creditVersion=b["version"],
            amount=21,
        ),
        400,
    )
    command(
        c,
        h,
        "reconcile",
        dict(
            debitLine=a["id"],
            creditLine=b["id"],
            debitVersion=a["version"],
            creditVersion=b["version"],
            amount=20,
        ),
    )
    items = c.get("/api/finance/open-items?partner=customer:one").json["items"]
    assert len(items) == 1
    assert Decimal(items[0]["openAmount"]) == 40
    assert c.get("/api/finance/open-items?partner=").json["items"] == []
    different = post(
        c, h, journal(c, h, 10, debit="1010", credit="1100", partner="customer:other")
    )
    other = next(l for l in different["lines"] if l["account"] == "1100")
    remaining = c.get("/api/finance/lines/" + str(a["id"])).json["record"]
    command(
        c,
        h,
        "reconcile",
        dict(
            debitLine=remaining["id"],
            creditLine=other["id"],
            debitVersion=remaining["version"],
            creditVersion=other["version"],
            amount=1,
        ),
        400,
    )
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Reconciliation)) == 2
    command(
        c,
        h,
        "reverse",
        dict(id=invoice["id"], version=details(c, invoice)["version"]),
        409,
    )


def test_bank_candidates_signed_matching_and_duplicate_item_rejection(app):
    c, h = session(app)
    j = post(c, h, journal(c, h, 120))
    line = next(l for l in j["lines"] if l["account"] == "1010")
    s = command(
        c,
        h,
        "statement",
        dict(
            date="2026-10-01",
            description="Capital statement",
            account="1010",
            amount=120,
        ),
    )
    candidates = c.get("/api/finance/statements/" + str(s["id"]) + "/candidates").json
    assert candidates["total"] == 1 and candidates["items"][0]["id"] == line["id"]
    payload = dict(
        requestKey="bank-match-repeat",
        id=s["id"],
        version=s["version"],
        lineId=line["id"],
        lineVersion=line["version"],
    )
    matched = command(c, h, "match-bank", payload)
    assert matched["matchedLine"] == line["id"]
    command(c, h, "match-bank", payload)
    other = command(
        c,
        h,
        "statement",
        dict(
            date="2026-10-01",
            description="Duplicate statement row",
            account="1010",
            amount=120,
        ),
    )
    assert (
        c.get("/api/finance/statements/" + str(other["id"]) + "/candidates").json[
            "items"
        ]
        == []
    )
    command(
        c,
        h,
        "match-bank",
        {
            **payload,
            "requestKey": "different-match-key",
            "id": other["id"],
            "version": other["version"],
        },
        409,
    )
    command(c, h, "reverse", dict(id=j["id"], version=details(c, j)["version"]), 409)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 1

    transfer = command(
        c,
        h,
        "transfer",
        dict(fromAccount="1010", toAccount="1000", amount=25, date="2026-10-01"),
    )
    negative = command(
        c,
        h,
        "statement",
        dict(
            account="1010", amount=-25, date="2026-10-01", description="Bank withdrawal"
        ),
    )
    candidate = c.get(
        "/api/finance/statements/" + str(negative["id"]) + "/candidates"
    ).json["items"][0]
    assert candidate["amount"] == "-25.00"
    command(
        c,
        h,
        "match-bank",
        dict(
            id=negative["id"],
            version=negative["version"],
            lineId=candidate["id"],
            lineVersion=candidate["version"],
        ),
    )


def test_period_lock_admin_stale_and_posting_rollback(app):
    c, h = session(app)
    j = journal(c, h, date="2026-10-01")
    initial = c.get("/api/finance/period-lock").json["record"]
    record = command(
        c, h, "period-lock", dict(date="2026-10-15", version=initial["version"])
    )
    command(c, h, "post", dict(id=j["id"], version=j["version"]), 400)
    assert details(c, j)["status"] == "Draft"
    command(c, h, "period-lock", dict(date=None, version=initial["version"]), 409)
    f, fh = finance_user(app)
    command(f, fh, "period-lock", dict(date=None, version=record["version"]), 403)
    command(c, h, "period-lock", dict(date=None, version=record["version"]))
    assert post(c, h, j)["status"] == "Posted"


def test_account_creation_export_csv_and_schema_upgrade_no_repost(app):
    c, h = session(app)
    account = command(
        c,
        h,
        "account",
        dict(
            code="1999",
            name="Native account",
            type="asset",
            reconcile=True,
            requestKey="account-repeat-key",
        ),
    )
    assert (
        command(
            c,
            h,
            "account",
            dict(
                code="1999",
                name="Native account",
                type="asset",
                reconcile=True,
                requestKey="account-repeat-key",
            ),
        )["code"]
        == "1999"
    )
    j = post(c, h, journal(c, h, debit="1999", memo="=dangerous-formula"))
    export = c.get("/api/finance/ledger/export?pageSize=1")
    assert export.status_code == 200
    assert "'=dangerous-formula" in export.text
    assert export.text.count("\n") == 2
    assert c.get("/api/finance/accounts?search=Native").json["total"] == 1
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    assert details(c, j)["status"] == "Posted"
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 1


def test_financial_journal_access_does_not_grant_private_hr_source(app):
    from backend.test_hr_api import (
        employee as hr_employee,
        payroll as hr_payroll,
        action as hr_action,
    )

    c, h = session(app)
    employee = hr_employee(c, h)
    payroll = hr_payroll(c, h, employee)
    hr_action(c, h, "payroll", payroll, "approve")
    with app.app_context():
        identity = db.session.scalar(
            select(JournalEntry.id).where(
                JournalEntry.source == "payroll:" + payroll["id"]
            )
        )
    admin = c.get("/api/finance/entries/" + str(identity))
    assert admin.status_code == 200
    assert (
        admin.json["record"]["sourceLink"]["href"]
        == "/api/hr/records/payroll/" + payroll["id"] + "/print"
    )
    f, fh = finance_user(app)
    financial = f.get("/api/finance/entries/" + str(identity))
    assert (
        financial.status_code == 200 and financial.json["record"]["sourceLink"] is None
    )
    assert (
        f.get("/api/hr/records/payroll/" + payroll["id"] + "/print").status_code == 403
    )
