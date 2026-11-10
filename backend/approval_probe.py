"""Isolated approval-enabled service baseline; never production HTTP capacity certification."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from threading import Barrier
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

from .app import create_app, db, User
from .approvals import ApprovalPolicy, ApprovalRequest
from .capacity_probe import distribution, seed, validate_database
from .erp import Expense, JournalEntry
from .workflow_health import report


def run_case(app, workers, iterations, password, label):
    clients = []
    for i in range(workers):
        pair = []
        for email in (f"capacity-{i}@example.test", "probe-finance@example.test"):
            client = app.test_client()
            response = client.post(
                "/api/auth/login", json={"email": email, "password": password}
            )
            if response.status_code != 200:
                raise RuntimeError("Probe login failed")
            pair.append((client, {"X-CSRF-Token": response.json["csrfToken"]}))
        clients.append(pair)
    with app.app_context():
        before = db.session.scalar(select(func.count()).select_from(JournalEntry))
    barrier = Barrier(workers)

    def worker(i):
        (maker, mh), (finance, fh) = clients[i]
        samples, statuses, errors = [], {}, []
        complete = 0

        def call(client, headers, operation, path, payload, expected):
            started = perf_counter()
            response = client.post("/api" + path, headers=headers, json=payload)
            samples.append(
                {"operation": operation, "ms": (perf_counter() - started) * 1000}
            )
            key = str(response.status_code)
            statuses[key] = statuses.get(key, 0) + 1
            if response.status_code != expected:
                # No request payloads, identifiers or credentials in the saved report.
                raise RuntimeError(
                    f"{operation}: expected {expected}, received {response.status_code}"
                )
            return response.json

        barrier.wait(timeout=30)
        for j in range(iterations):
            prefix = f"approval-probe-{label}-{i}-{j}"
            try:
                expense = call(
                    maker,
                    mh,
                    "create",
                    "/expenses/commands/create",
                    {
                        "description": prefix,
                        "amount": 25,
                        "tax": 0,
                        "requestKey": prefix + "-create",
                    },
                    200,
                )["record"]
                expense = call(
                    maker,
                    mh,
                    "submit",
                    "/expenses/commands/submit",
                    {
                        "id": expense["id"],
                        "version": expense["version"],
                        "requestKey": prefix + "-submit",
                    },
                    200,
                )["record"]
                row = call(
                    maker,
                    mh,
                    "request approval",
                    "/expenses/commands/approve",
                    {
                        "id": expense["id"],
                        "version": expense["version"],
                        "requestKey": prefix + "-review",
                    },
                    202,
                )["approval"]
                path = f"/approvals/requests/{row['id']}/approve"
                decision = {
                    "version": row["version"],
                    "reason": "Independent synthetic service baseline review",
                }
                call(maker, mh, "block self approval", path, decision, 403)
                expense = call(finance, fh, "approve expense", path, decision, 200)[
                    "result"
                ]["record"]
                row = call(
                    maker,
                    mh,
                    "request payment",
                    "/expenses/commands/pay",
                    {
                        "id": expense["id"],
                        "version": expense["version"],
                        "account": "1010",
                        "date": expense["date"],
                        "requestKey": prefix + "-pay",
                    },
                    202,
                )["approval"]
                path = f"/approvals/requests/{row['id']}/approve"
                decision = {
                    "version": row["version"],
                    "reason": "Independent synthetic payment review",
                }
                paid = call(finance, fh, "approve payment", path, decision, 200)[
                    "result"
                ]["record"]
                call(finance, fh, "block duplicate decision", path, decision, 409)
                if paid["status"] != "Paid":
                    raise RuntimeError("Independent payment did not settle expense")
                complete += 1
            except RuntimeError as error:
                errors.append(str(error))
        return samples, statuses, complete, errors

    started = perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(worker, range(workers)))
    elapsed = perf_counter() - started
    samples = [sample for rows, _, _, _ in results for sample in rows]
    statuses = {}
    for _, codes, _, _ in results:
        for code, count in codes.items():
            statuses[code] = statuses.get(code, 0) + count
    expected = workers * iterations
    with app.app_context():
        journal_count = (
            db.session.scalar(select(func.count()).select_from(JournalEntry)) - before
        )
        paid = db.session.scalars(
            select(Expense).where(Expense.description.like(f"approval-probe-{label}-%"))
        ).all()
        approvals = db.session.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(
                ApprovalRequest.target.in_([str(e.id) for e in paid]),
                ApprovalRequest.status == "Approved",
            )
        )
        health = report()
    errors = [error for _, _, _, group in results for error in group]
    passed = (
        not errors
        and sum(done for _, _, done, _ in results) == expected
        and statuses
        == {"200": expected * 4, "202": expected * 2, "403": expected, "409": expected}
        and journal_count == expected * 2
        and len(paid) == expected
        and all(e.status == "Paid" and e.amount == 25 for e in paid)
        and approvals == expected * 2
        and health["healthy"]
    )
    return {
        "workers": workers,
        "iterationsPerWorker": iterations,
        "seconds": round(elapsed, 3),
        "completedWorkflows": sum(done for _, _, done, _ in results),
        "expectedWorkflows": expected,
        "requestCount": len(samples),
        "requestsPerSecond": round(len(samples) / elapsed, 3),
        "responseMs": distribution([s["ms"] for s in samples]),
        "statusCounts": statuses,
        "expectedDenials": {"403": expected, "409": expected},
        "unexpectedFailures": errors,
        "operations": {
            op: distribution([s["ms"] for s in samples if s["operation"] == op])
            for op in sorted({s["operation"] for s in samples})
        },
        "newJournals": journal_count,
        "approvedRequests": approvals,
        "paidExpenses": len(paid),
        "health": health,
        "passed": passed,
    }


def execute(url, rows=1000, workers=(1, 4, 8), iterations=3):
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
        {
            "SQLALCHEMY_DATABASE_URI": url,
            "COOKIE_SECURE": False,
            "TESTING": True,
            "APPROVAL_CONTROLS_ENABLED": True,
        }
    )
    password = secrets.token_urlsafe(32)
    try:
        seed(app, rows, max(workers), password)
        with app.app_context():
            db.session.add(
                User(
                    id="probe-finance",
                    name="Independent Finance",
                    email="probe-finance@example.test",
                    role="Finance",
                    active=True,
                    password_hash=generate_password_hash(password),
                )
            )
            db.session.flush()
            for user in db.session.scalars(
                select(User).where(User.id.like("capacity-%"))
            ):
                user.manager_id = "probe-finance"
            db.session.add(
                ApprovalPolicy(
                    id=1, limits={"Admin": "1000000.00", "Finance": "1000000.00"}
                )
            )
            db.session.commit()
        cases = [
            run_case(app, w, iterations, password, f"case-{i}")
            for i, w in enumerate(workers)
        ]
        return {
            "schemaVersion": 1,
            "mode": "in-process closed-loop service baseline; no HTTP or multi-process workers",
            "approvalEnforcement": True,
            "database": make_url(url).get_backend_name(),
            "historicalEmployees": rows,
            "historicalPurchaseRequests": rows,
            "cases": cases,
            "passed": all(c["passed"] for c in cases),
        }
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 4, 8])
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="approval-capacity-") as directory:
        url = os.environ.get("CAPACITY_DATABASE_URL") or "sqlite:///" + str(
            Path(directory) / "capacity-probe.sqlite"
        )
        result = execute(url, args.rows, args.workers, args.iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "database": result["database"],
                "cases": len(result["cases"]),
            }
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
