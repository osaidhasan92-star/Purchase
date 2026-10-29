"""Repeatable, isolated API-service baseline; never a production capacity certificate."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from math import ceil
import json
import os
from pathlib import Path
import platform
import secrets
from tempfile import TemporaryDirectory
from threading import Barrier, local
from time import perf_counter

from sqlalchemy import create_engine, event, inspect, select, func
from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

from .app import create_app, db, User
from . import hr_store as hr, trade_store as trade
from .erp import JournalEntry
from .workflow_health import report as health
from .workflow_keys import ConflictKey, tokens


def validate_database(url):
    """Refuse existing schemas and non-dedicated names, without dropping anything."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "postgresql":
        if parsed.database != "purchase_capacity_test":
            raise ValueError("Use a fresh dedicated purchase_capacity_test database")
    elif parsed.get_backend_name() == "sqlite":
        if not parsed.database or Path(parsed.database).name != "capacity-probe.sqlite":
            raise ValueError("Use a fresh file named capacity-probe.sqlite")
        if Path(parsed.database).exists():
            raise ValueError(
                "Capacity database file already exists; use a fresh directory"
            )
    else:
        raise ValueError("Only isolated SQLite or PostgreSQL databases are supported")
    engine = create_engine(url)
    try:
        if inspect(engine).get_table_names():
            raise ValueError("Capacity database must be empty; nothing was changed")
    finally:
        engine.dispose()


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return dict(count=0, p50=0, p95=0, p99=0, maximum=0)
    return dict(
        count=len(ordered),
        **{
            f"p{p}": round(ordered[max(0, ceil(len(ordered) * p / 100) - 1)], 3)
            for p in (50, 95, 99)
        },
        maximum=round(ordered[-1], 3),
    )


def seed(app, rows, workers, password):
    result = app.test_cli_runner().invoke(args=["init-db"])
    if result.exit_code:
        raise RuntimeError("Isolated schema initialization failed")
    with app.app_context():
        password_hash = generate_password_hash(password)
        for i in range(workers):
            db.session.add(
                User(
                    id=f"capacity-{i}",
                    name="Synthetic load operator",
                    email=f"capacity-{i}@example.test",
                    role="Admin",
                    active=True,
                    password_hash=password_hash,
                )
            )
        db.session.commit()
        valid = {k: set() for k in hr.MODELS}
        valid["user"] = set()
        # Bounded batches keep preparation memory independent of fixture size.
        for start in range(0, rows, 500):
            employee_rows, request_rows, keys = [], [], []
            for i in range(start, min(rows, start + 500)):
                value = dict(
                    id=f"capacity-history-{i}",
                    employeeId=f"HIST-{i}",
                    name=f"Synthetic historical employee {i}",
                    department="Archive",
                    status="Active",
                    joiningDate="2020-01-01",
                    salary=10000,
                )
                employee = hr.Employee(id=value["id"])
                hr.write_one("employees", value, employee, i + 100, valid, [])
                employee_rows.append(
                    {
                        c.name: getattr(employee, c.name)
                        for c in employee.__table__.columns
                    }
                )
                request = dict(
                    id=f"capacity-request-{i}",
                    requestNo=f"HIST-REQ-{i}",
                    department="Archive",
                    status="Draft",
                    items=0,
                    total=0,
                    lineItems=[],
                )
                row = trade.MODELS["requests"](id=request["id"], position=i + 100)
                trade.assign_header("requests", request, row, trade.available_ids({}))
                request_rows.append(
                    {c.name: getattr(row, c.name) for c in row.__table__.columns}
                )
                for key, record in (("employees", value), ("requests", request)):
                    keys.extend(
                        dict(domain=key, kind=kind, record_id=record["id"], token=token)
                        for kind, token in tokens(key, record).items()
                    )
            db.session.execute(hr.Employee.__table__.insert(), employee_rows)
            db.session.execute(
                trade.MODELS["requests"].__table__.insert(), request_rows
            )
            db.session.execute(ConflictKey.__table__.insert(), keys)
            db.session.commit()


def run_case(app, workers, iterations, password, label):
    """Independent clients, synchronized start, closed-loop load with no think time."""
    clients = []
    for i in range(workers):
        c = app.test_client()
        login = c.post(
            "/api/auth/login",
            json=dict(email=f"capacity-{i}@example.test", password=password),
        )
        if login.status_code != 200:
            raise RuntimeError("Synthetic login failed")
        headers = {"X-CSRF-Token": login.json["csrfToken"]}
        employee = c.post(
            "/api/hr/records/employees",
            headers=headers,
            json=dict(
                requestKey=f"capacity-{label}-employee-{i}",
                employeeId=f"EMP-{label}-{i}",
                name=f"Load employee {label} {i}",
                department="Production",
                designation="Operator",
                joiningDate="2020-01-01",
                salary=10000,
            ),
        )
        if employee.status_code != 200:
            raise RuntimeError("Synthetic employee setup failed")
        clients.append((c, headers, employee.json["record"]["id"]))

    measurements = local()
    barrier = Barrier(workers)
    with app.app_context():
        engine = db.engine
        before_entries = db.session.scalar(
            select(func.count()).select_from(JournalEntry)
        )
        before_paid = db.session.scalar(
            select(func.count())
            .select_from(hr.Payroll)
            .where(hr.Payroll.status == "Paid")
        )
        before_net = db.session.scalar(
            select(func.coalesce(func.sum(hr.Payroll.net_pay), 0)).where(
                hr.Payroll.status == "Paid"
            )
        )

    def before(conn, cursor, statement, parameters, context, many):
        if getattr(measurements, "active", False):
            context.capacity_started = perf_counter()
            measurements.queries += 1

    def after(conn, cursor, statement, parameters, context, many):
        if getattr(
            measurements, "active", False
        ) and statement.lstrip().upper().startswith("UPDATE ERP_CONTROL "):
            measurements.lock_ms += (perf_counter() - context.capacity_started) * 1000

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)

    def worker(i):
        c, headers, employee_id = clients[i]
        samples, statuses = [], {}
        complete = 0

        def request(method, path, payload=None):
            measurements.active = True
            measurements.queries = 0
            measurements.lock_ms = 0.0
            start = perf_counter()
            try:
                response = c.open(path, method=method, headers=headers, json=payload)
                elapsed = (perf_counter() - start) * 1000
                statuses[str(response.status_code)] = (
                    statuses.get(str(response.status_code), 0) + 1
                )
                samples.append(
                    dict(
                        operation=(
                            path.split("?")[0]
                            if method == "GET"
                            else method + " payroll"
                        ),
                        ms=elapsed,
                        queries=measurements.queries,
                        lockStatementMs=measurements.lock_ms,
                    )
                )
                return response.json if response.status_code == 200 else None
            finally:
                measurements.active = False

        barrier.wait(timeout=30)
        for j in range(iterations):
            for path in (
                "/api/trade/requests?pageSize=25",
                "/api/hr/records/employees?pageSize=25",
                "/api/finance/summary",
            ):
                request("GET", path)
            prefix = f"capacity-{label}-{i}-{j}"
            payload = dict(
                requestKey=prefix + "-create",
                employeeKey=employee_id,
                month=f"{2020 + j // 12:04d}-{j % 12 + 1:02d}",
                basic=10000,
                allowances=500,
                deductions=100,
            )
            created = request("POST", "/api/hr/records/payroll", payload)
            if not created:
                continue
            row = created["record"]
            ok = True
            for action in ("approve", "pay"):
                path = f'/api/hr/records/payroll/{row["id"]}/actions/{action}'
                payload = dict(requestKey=prefix + "-" + action, version=row["version"])
                response = request("POST", path, payload)
                if not response:
                    ok = False
                    break
                # Replay the exact command. It must not create a second journal/payment.
                replay = request("POST", path, payload)
                if not replay or replay["record"]["id"] != row["id"]:
                    ok = False
                row = response["record"]
            complete += int(ok and row["status"] == "Paid")
        return samples, statuses, complete

    start = perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(worker, range(workers)))
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
    elapsed = perf_counter() - start
    samples = [s for sample, _, _ in results for s in sample]
    statuses = {}
    for _, codes, _ in results:
        for code, count in codes.items():
            statuses[code] = statuses.get(code, 0) + count
    with app.app_context():
        after_entries = db.session.scalar(
            select(func.count()).select_from(JournalEntry)
        )
        paid = db.session.scalar(
            select(func.count())
            .select_from(hr.Payroll)
            .where(hr.Payroll.status == "Paid")
        )
        net = db.session.scalar(
            select(func.coalesce(func.sum(hr.Payroll.net_pay), 0)).where(
                hr.Payroll.status == "Paid"
            )
        )
        checks = health()
    completed = sum(done for _, _, done in results)
    expected = workers * iterations
    return dict(
        workers=workers,
        iterationsPerWorker=iterations,
        seconds=round(elapsed, 3),
        requests=len(samples),
        requestsPerSecond=round(len(samples) / elapsed, 3),
        statusCounts=statuses,
        responseMs=distribution([s["ms"] for s in samples]),
        queriesPerRequest=distribution([s["queries"] for s in samples]),
        lockStatementMs=distribution(
            [s["lockStatementMs"] for s in samples if s["lockStatementMs"] > 0]
        ),
        operations={
            op: distribution([s["ms"] for s in samples if s["operation"] == op])
            for op in sorted({s["operation"] for s in samples})
        },
        completedWorkflows=completed,
        expectedWorkflows=expected,
        newJournals=after_entries - before_entries,
        totalPaidPayroll=paid,
        health=checks,
        passed=(
            completed == expected
            and statuses == {"200": len(samples)}
            and after_entries - before_entries == expected * 2
            and paid - before_paid == expected
            and net - before_net == expected * 10400
            and checks["healthy"]
        ),
    )


def execute(url, rows, workers, iterations):
    if (
        rows < 1
        or iterations < 1
        or iterations > 120
        or not workers
        or any(w < 1 or w > 100 for w in workers)
    ):
        raise ValueError("Use rows >= 1, iterations 1..120, workers 1..100")
    validate_database(url)
    app = create_app(
        dict(SQLALCHEMY_DATABASE_URI=url, COOKIE_SECURE=False, TESTING=True)
    )
    password = secrets.token_urlsafe(32)
    try:
        seed(app, rows, max(workers), password)
        cases = [
            run_case(app, w, iterations, password, f"case-{i}")
            for i, w in enumerate(workers)
        ]
        return dict(
            schemaVersion=1,
            mode="in-process threaded Flask API service; no HTTP/network or multi-process workers",
            database=make_url(url).get_backend_name(),
            python=platform.python_version(),
            platform=platform.system(),
            logicalCPUs=os.cpu_count(),
            historicalEmployees=rows,
            historicalPurchaseRequests=rows,
            cases=cases,
            passed=all(c["passed"] for c in cases),
        )
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 4, 8])
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="purchase-capacity-") as directory:
        url = os.environ.get("CAPACITY_DATABASE_URL") or "sqlite:///" + str(
            Path(directory) / "capacity-probe.sqlite"
        )
        result = execute(url, args.rows, args.workers, args.iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            dict(
                passed=result["passed"],
                database=result["database"],
                cases=len(result["cases"]),
            )
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
