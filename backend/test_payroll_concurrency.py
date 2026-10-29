"""Payroll amount conservation, process races, period locks and atomic rollback."""

from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from threading import Barrier
import pytest
from sqlalchemy import select, func
from backend.test_app import app, session
from backend.test_resource_concurrency import employee, make_record, require_postgres
from backend.app import db, Document
from backend.hr_store import Payroll
from backend.erp import ERPControl, JournalEntry, JournalLine, Reconciliation, day
from backend.backup_verify import snapshot


def action(c, h, row, command, key):
    return c.post(
        "/api/hr/records/payroll/" + row["id"] + "/actions/" + command,
        headers=h,
        json=dict(requestKey=key, version=row["version"]),
    )


def test_payroll_duplicate_month_and_month_edit_are_guarded(app):
    c, h = session(app)
    parent = employee(c, h, "payroll-month-parent")
    clients = [session(app), session(app)]
    barrier = Barrier(2)

    def create(i):
        client, headers = clients[i]
        barrier.wait(timeout=10)
        return client.post(
            "/api/hr/records/payroll",
            headers=headers,
            json=dict(
                requestKey="payroll-month-" + str(i),
                employeeKey=parent["id"],
                month="2026-10",
                basic=10000,
            ),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, range(2))) == [200, 409]
    r = c.post(
        "/api/hr/records/payroll",
        headers=h,
        json=dict(
            requestKey="payroll-next-month",
            employeeKey=parent["id"],
            month="2026-11",
            basic=10000,
        ),
    )
    assert r.status_code == 200, r.json
    row = r.json["record"]
    assert (
        c.patch(
            "/api/hr/records/payroll/" + row["id"],
            headers=h,
            json=dict(
                requestKey="payroll-edit-month", version=row["version"], month="2026-10"
            ),
        ).status_code
        == 409
    )


def test_payroll_approval_and_payment_races_post_once_and_replay(app):
    c, h = session(app)
    row = make_record(c, h, "payroll-race-setup", "payroll")
    clients = [session(app), session(app)]
    for command in ("approve", "pay"):
        barrier = Barrier(2)

        def race(i):
            client, headers = clients[i]
            barrier.wait(timeout=10)
            return action(
                client, headers, row, command, "payroll-race-" + command + str(i)
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(race, range(2)))
        assert sorted(r.status_code for r in responses) == [200, 409]
        winner = next(i for i, r in enumerate(responses) if r.status_code == 200)
        replay = action(
            *clients[winner], row, command, "payroll-race-" + command + str(winner)
        )
        assert replay.status_code == 200
        row = replay.json["record"]
    assert row["status"] == "Paid"
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 2
        assert db.session.scalar(select(func.count()).select_from(Reconciliation)) == 1
        for entry in db.session.scalars(select(JournalEntry)):
            assert sum(l.debit for l in entry.lines) == sum(
                l.credit for l in entry.lines
            )
        balances = dict(
            db.session.execute(
                select(
                    JournalLine.account,
                    func.sum(JournalLine.debit - JournalLine.credit),
                ).group_by(JournalLine.account)
            ).all()
        )
        assert balances == {"6100": 10500, "2300": 0, "2310": -100, "1010": -10400}


def close_period(c, h, value, key):
    record = c.get("/api/finance/period-lock").json["record"]
    r = c.post(
        "/api/finance/commands/period-lock",
        headers=h,
        json=dict(requestKey=key, version=record["version"], date=value),
    )
    assert r.status_code == 200, r.json


def test_payroll_locked_approval_payment_roll_back_and_retry_same_key(app):
    c, h = session(app)
    row = make_record(c, h, "payroll-period-setup", "payroll")
    for command, status in (("approve", "Draft"), ("pay", "Approved")):
        close_period(c, h, day(), "payroll-lock-" + command)
        with app.app_context():
            before = snapshot(db.engine)
        r = action(c, h, row, command, "payroll-period-" + command)
        assert r.status_code == 400, r.json
        with app.app_context():
            assert snapshot(db.engine) == before
            assert db.session.get(Payroll, row["id"]).status == status
        close_period(c, h, None, "payroll-unlock-" + command)
        r = action(c, h, row, command, "payroll-period-" + command)
        assert r.status_code == 200, r.json
        row = r.json["record"]


def test_payroll_posting_failure_rolls_back_journal_matching_scopes_and_receipt(
    app, monkeypatch
):
    from backend import erp
    from backend.validation import InvalidBusinessState

    c, h = session(app)
    row = make_record(c, h, "payroll-rollback-setup", "payroll")
    row = action(c, h, row, "approve", "payroll-rollback-approve").json["record"]
    original = erp.auto_reconcile

    def fail(*args):
        original(*args)
        raise InvalidBusinessState("Injected failure after reconciliation")

    with app.app_context():
        before = snapshot(db.engine)
    monkeypatch.setattr(erp, "auto_reconcile", fail)
    r = action(c, h, row, "pay", "payroll-rollback-pay")
    assert r.status_code == 400, r.json
    with app.app_context():
        assert snapshot(db.engine) == before
    monkeypatch.setattr(erp, "auto_reconcile", original)
    assert action(c, h, row, "pay", "payroll-rollback-pay").status_code == 200


def _process_payroll(url, identity, version, key, barrier, output):
    from backend.app import create_app
    from backend.hr_context import Context

    application = create_app(
        dict(SQLALCHEMY_DATABASE_URI=url, TESTING=True, COOKIE_SECURE=False)
    )
    original = Context.validate

    def validate(self):
        original(self)
        barrier.wait(timeout=20)

    Context.validate = validate
    try:
        c, h = session(application)
        row = dict(id=identity, version=version)
        for command in ("approve", "pay"):
            r = action(c, h, row, command, key + "-" + command)
            if r.status_code != 200:
                output.put(dict(status=r.status_code))
                return
            row = r.json["record"]
        output.put(dict(status=200))
    except Exception as error:
        output.put(dict(failure=type(error).__name__))
    finally:
        with application.app_context():
            db.session.remove()
            db.engine.dispose()


def test_postgres_payroll_processes_prepare_in_parallel_and_post_balanced_payments(app):
    require_postgres(app)
    c, h = session(app, "hr")
    rows = [make_record(c, h, "payroll-process-" + str(i), "payroll") for i in range(2)]
    with app.app_context():
        control = db.session.get(ERPControl, 1).revision
    ctx = multiprocessing.get_context("spawn")
    barrier, output = ctx.Barrier(2), ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_payroll,
            args=(
                app.config["SQLALCHEMY_DATABASE_URI"],
                row["id"],
                row["version"],
                "payroll-worker-" + str(i),
                barrier,
                output,
            ),
        )
        for i, row in enumerate(rows)
    ]
    try:
        for p in processes:
            p.start()
        results = [output.get(timeout=45) for p in processes]
        for p in processes:
            p.join(timeout=10)
        assert results == [dict(status=200), dict(status=200)], results
        assert all(p.exitcode == 0 for p in processes)
        with app.app_context():
            assert db.session.get(ERPControl, 1).revision == control
            entries = db.session.scalars(select(JournalEntry)).all()
            assert len(entries) == 4 and len({e.number for e in entries}) == 4
            scopes = db.session.get(Document, "record_scopes").stored_data
            for e in entries:
                assert e.created_by == "hr"
                assert scopes["journal_entry:" + str(e.id)] == "hr"
                assert sum(l.debit for l in e.lines) == sum(l.credit for l in e.lines)
            assert (
                db.session.scalar(select(func.count()).select_from(Reconciliation)) == 2
            )
            assert (
                db.session.scalar(
                    select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                        JournalLine.account == "2300"
                    )
                )
                == 0
            )
    finally:
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)
        output.close()


def test_postgres_payroll_posting_mutex_timeout_rolls_back_and_retries(app):
    require_postgres(app)
    c, h = session(app)
    row = make_record(c, h, "payroll-mutex-setup", "payroll")
    app.config["ERP_LOCK_TIMEOUT_MS"] = 50
    with app.app_context():
        db.session.execute(select(func.pg_advisory_xact_lock(1346459986, 1)))
        with ThreadPoolExecutor(max_workers=1) as pool:
            r = pool.submit(
                lambda: action(c, h, row, "approve", "payroll-mutex-approve")
            ).result(timeout=10)
        assert r.status_code == 503, r.json
        db.session.rollback()
        assert db.session.get(Payroll, row["id"]).status == "Draft"
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 0
    assert action(c, h, row, "approve", "payroll-mutex-approve").status_code == 200


def test_payroll_cannot_issue_another_payment_after_external_matching(app):
    from flask import g
    from backend.app import User
    from backend import erp

    c, h = session(app)
    row = make_record(c, h, "payroll-external-setup", "payroll")
    row = action(c, h, row, "approve", "payroll-external-approve").json["record"]
    with app.test_request_context():
        g.user = db.session.get(User, "admin")
        erp.lock()
        invoice = db.session.scalar(
            select(JournalEntry).where(JournalEntry.source == "payroll:" + row["id"])
        )
        liability = next(l for l in invoice.lines if l.account == "2300")
        payment = erp.journal_pair(
            "manual:external-salary-payment",
            "External salary payment",
            "2300",
            "1010",
            10400,
            partner=liability.partner,
        )
        erp.auto_reconcile(invoice.source, payment, "2300")
        db.session.commit()
    with app.app_context():
        before = snapshot(db.engine)
    response = action(c, h, row, "pay", "payroll-external-pay")
    assert response.status_code == 400, response.json
    assert "Accounting" in response.json["error"]
    with app.app_context():
        assert snapshot(db.engine) == before


def test_postgres_period_close_waits_for_inflight_payroll_then_blocks_new_posting(
    app, monkeypatch
):
    from threading import Event
    from backend import erp

    require_postgres(app)
    c, h = session(app)
    finance, fh = session(app)
    row = make_record(c, h, "payroll-close-race-setup", "payroll")
    app.config["ERP_LOCK_TIMEOUT_MS"] = 50
    entered, release = Event(), Event()
    original = erp.sync_payroll

    def paused(previous, current):
        entered.set()
        assert release.wait(timeout=10)
        return original(previous, current)

    monkeypatch.setattr(erp, "sync_payroll", paused)
    control = finance.get("/api/finance/period-lock").json["record"]
    body = dict(requestKey="payroll-close-race", version=control["version"], date=day())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            lambda: action(c, h, row, "approve", "payroll-close-race-approve")
        )
        try:
            assert entered.wait(timeout=10)
            response = finance.post(
                "/api/finance/commands/period-lock", headers=fh, json=body
            )
            assert response.status_code == 503, response.json
        finally:
            release.set()
        response = future.result(timeout=10)
    assert response.status_code == 200, response.json
    monkeypatch.setattr(erp, "sync_payroll", original)
    response = finance.post("/api/finance/commands/period-lock", headers=fh, json=body)
    assert response.status_code == 200, response.json
    other = make_record(c, h, "payroll-after-close-setup", "payroll")
    response = action(c, h, other, "approve", "payroll-after-close-approve")
    assert response.status_code == 400, response.json
    with app.app_context():
        assert db.session.get(Payroll, other["id"]).status == "Draft"
        assert db.session.scalar(select(func.count()).select_from(JournalEntry)) == 1
