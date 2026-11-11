"""Isolated recovery drill: exact data, attachments and independent posting after restore."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path

from sqlalchemy import MetaData, create_engine, inspect, select
from sqlalchemy.engine import make_url

PASSWORD = "Isolated-backup-drill-only-42"
RECEIPT = b"%PDF-1.4\nIsolated recovery drill receipt\n%%EOF\n"


def snapshot(engine):
    meta = MetaData()
    meta.reflect(engine)
    result = {}

    def encode(v):
        return hashlib.sha256(v).hexdigest() if isinstance(v, bytes) else str(v)

    with engine.connect() as conn:
        for name, table in meta.tables.items():
            rows = [
                json.dumps(
                    dict(r._mapping),
                    sort_keys=True,
                    default=encode,
                    separators=(",", ":"),
                )
                for r in conn.execute(select(table))
            ]
            result[name] = (
                len(rows),
                hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest(),
            )
    return result


def validate_url(value, kind):
    """Resolve dedicated names before opening a connection; no production fallback."""
    parsed = make_url(value)
    name = "purchase_backup_" + kind
    if parsed.get_backend_name() == "postgresql":
        valid = parsed.database == name
    elif parsed.get_backend_name() == "sqlite":
        valid = (
            bool(parsed.database)
            and Path(parsed.database).is_absolute()
            and Path(parsed.database).name == name + ".sqlite"
        )
    else:
        valid = False
    if not valid:
        raise ValueError(
            "Use an isolated " + name + " database (absolute .sqlite path for SQLite)"
        )
    return value


def application(url, enforced=True):
    from .app import create_app

    return create_app(
        {
            "SQLALCHEMY_DATABASE_URI": url,
            "COOKIE_SECURE": False,
            "TESTING": True,
            "APPROVAL_CONTROLS_ENABLED": enforced,
        }
    )


def checked(response, expected=200):
    if response.status_code != expected:
        raise RuntimeError(
            f"Drill request failed ({response.status_code}, expected {expected}): {response.json}"
        )
    return response.json


def login(app, who):
    client = app.test_client()
    data = checked(
        client.post(
            "/api/auth/login",
            json={"email": who + "@example.test", "password": PASSWORD},
        )
    )
    return client, {"X-CSRF-Token": data["csrfToken"]}


def post(client, headers, path, data, expected=200):
    return checked(client.post("/api" + path, headers=headers, json=data), expected)


def decision(client, headers, row):
    return post(
        client,
        headers,
        f"/approvals/requests/{row['id']}/approve",
        {
            "version": row["version"],
            "reason": "Independent review after database recovery",
        },
    )


def prepare(source):
    validate_url(source, "source")
    engine = create_engine(source)
    try:
        if inspect(engine).get_table_names():
            raise ValueError("Backup source must be a fresh empty CI database")
    finally:
        engine.dispose()
    from .app import db, User
    from .approvals import ApprovalPolicy
    from werkzeug.security import generate_password_hash

    # Initial synthetic opening balances only. All subsequent requests use enforcement.
    app = application(source, enforced=False)
    try:
        result = app.test_cli_runner().invoke(args=["init-db"])
        if result.exit_code:
            raise RuntimeError(
                "Isolated schema initialization failed: " + result.output
            )
        with app.app_context():
            for who, role in (("backup-admin", "Admin"), ("backup-finance", "Finance")):
                db.session.add(
                    User(
                        id=who,
                        name=who,
                        email=who + "@example.test",
                        role=role,
                        active=True,
                        password_hash=generate_password_hash(PASSWORD),
                    )
                )
            db.session.add(
                ApprovalPolicy(
                    id=1, limits={"Admin": "1000000.00", "Finance": "1000000.00"}
                )
            )
            db.session.commit()
        c, h = login(app, "backup-admin")
        post(c, h, "/erp/seed-demo", {})
        app.config["APPROVAL_CONTROLS_ENABLED"] = True
        receipt = checked(
            c.post(
                "/api/attachments",
                headers=h,
                data={
                    "module": "expenses",
                    "file": (io.BytesIO(RECEIPT), "recovery-receipt.pdf"),
                },
            )
        )
        expense = post(
            c,
            h,
            "/expenses/commands/create",
            {
                "requestKey": "backup-expense",
                "description": "Restored receipt and approval drill",
                "amount": 25,
                "tax": 0,
                "attachmentId": receipt["attachmentPath"],
            },
        )["record"]
        post(
            c,
            h,
            "/expenses/commands/submit",
            {
                "id": expense["id"],
                "version": expense["version"],
                "requestKey": "backup-expense-submit",
            },
        )
        post(c, h, "/approvals/refresh", {})
        pending = checked(c.get("/api/approvals/requests"))["items"]
        if not any(row["resource"] == "expenses" for row in pending):
            raise RuntimeError("Pending expense approval missing from backup fixture")
        return {
            "prepared": True,
            "enforcementEnabled": True,
            "pendingApprovals": len(pending),
            "attachmentSha256": hashlib.sha256(RECEIPT).hexdigest(),
        }
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def compare(source, target):
    validate_url(source, "source")
    validate_url(target, "restore")
    left, right = create_engine(source), create_engine(target)
    try:
        a, b = snapshot(left), snapshot(right)
        if not a or a != b:
            raise RuntimeError("Restored database differs from the source")
    finally:
        left.dispose()
        right.dispose()
    from .app import db
    from .workflow_health import report

    app = application(target)
    try:
        c, h = login(app, "backup-admin")
        reviewer, rh = login(app, "backup-finance")
        pending = checked(reviewer.get("/api/approvals/requests"))["items"]
        row = next(r for r in pending if r["resource"] == "expenses")
        expense = checked(c.get("/api/expenses/claims/" + row["target"]))["record"]
        receipt = c.get("/api/attachments/" + expense["attachmentId"])
        if receipt.status_code != 200 or receipt.data != RECEIPT:
            raise RuntimeError("Restored attachment is missing or changed")
        checked(
            c.post(
                f"/api/approvals/requests/{row['id']}/approve",
                headers=h,
                json={
                    "version": row["version"],
                    "reason": "Self review must be rejected",
                },
            ),
            403,
        )
        decision(reviewer, rh, row)
        expense = checked(c.get("/api/expenses/claims/" + row["target"]))["record"]
        payment = post(
            c,
            h,
            "/expenses/commands/pay",
            {
                "id": expense["id"],
                "version": expense["version"],
                "requestKey": "restore-drill-pay",
                "account": "1010",
                "date": expense["date"],
            },
            202,
        )["approval"]
        if (
            checked(c.get("/api/expenses/claims/" + row["target"]))["record"]["status"]
            != "Approved"
        ):
            raise RuntimeError("Payment posted without independent approval")
        decision(reviewer, rh, payment)
        checked(
            reviewer.post(
                f"/api/approvals/requests/{payment['id']}/approve",
                headers=rh,
                json={
                    "version": payment["version"],
                    "reason": "Duplicate must not post",
                },
            ),
            409,
        )
        paid = checked(c.get("/api/expenses/claims/" + row["target"]))["record"]
        if (
            paid["status"] != "Paid"
            or float(checked(c.get("/api/finance/summary"))["balanceCheck"]) != 0
        ):
            raise RuntimeError("Restored workflow failed financial conservation")
        with app.app_context():
            health = report()
            if not health["healthy"]:
                raise RuntimeError("Restored workflow health failed")
        return {
            "tablesVerified": len(a),
            "rowsVerified": sum(v[0] for v in a.values()),
            "match": True,
            "attachmentVerified": True,
            "enforcementEnabled": True,
            "selfApprovalBlocked": True,
            "duplicateDecisionBlocked": True,
            "expensePaidAfterIndependentReview": True,
            "workflowHealth": health,
        }
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "compare"))
    args = parser.parse_args()
    source = os.environ["BACKUP_SOURCE_URL"]
    result = (
        prepare(source)
        if args.operation == "prepare"
        else compare(source, os.environ["BACKUP_RESTORE_URL"])
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
