"""Isolated CI backup drill helpers; never accept a production database name."""

import hashlib, json, os, sys
from sqlalchemy import create_engine, inspect, MetaData, select
from sqlalchemy.engine import make_url


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


def source_url():
    value = os.environ["BACKUP_SOURCE_URL"]
    if make_url(value).database != "purchase_backup_source":
        raise ValueError("Use an isolated purchase_backup_source database")
    return value


def main():
    source = source_url()
    if sys.argv[1] == "prepare":
        from .app import create_app, db, User
        from werkzeug.security import generate_password_hash

        engine = create_engine(source)
        if inspect(engine).get_table_names():
            raise ValueError("Backup source must be a fresh empty CI database")
        engine.dispose()
        app = create_app(
            {"SQLALCHEMY_DATABASE_URI": source, "COOKIE_SECURE": False, "TESTING": True}
        )
        assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
        password = "Isolated-backup-drill-only-42"
        with app.app_context():
            db.session.add(
                User(
                    id="backup-admin",
                    name="Backup test",
                    email="backup@example.test",
                    role="Admin",
                    active=True,
                    password_hash=generate_password_hash(password),
                )
            )
            db.session.commit()
        c = app.test_client()
        login = c.post(
            "/api/auth/login",
            json={"email": "backup@example.test", "password": password},
        )
        assert login.status_code == 200
        assert (
            c.post(
                "/api/erp/seed-demo",
                headers={"X-CSRF-Token": login.json["csrfToken"]},
                json={},
            ).status_code
            == 200
        )
        print("Isolated backup fixture prepared with stock, journals and account data.")
    elif sys.argv[1] == "compare":
        target = os.environ["BACKUP_RESTORE_URL"]
        if make_url(target).database != "purchase_backup_restore":
            raise ValueError("Use an isolated purchase_backup_restore database")
        left, right = create_engine(source), create_engine(target)
        a, b = snapshot(left), snapshot(right)
        assert a == b, "Restored database differs from the source"
        left.dispose()
        right.dispose()
        from .app import create_app

        app = create_app(
            {"SQLALCHEMY_DATABASE_URI": target, "COOKIE_SECURE": False, "TESTING": True}
        )
        c = app.test_client()
        login = c.post(
            "/api/auth/login",
            json={
                "email": "backup@example.test",
                "password": "Isolated-backup-drill-only-42",
            },
        )
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json["csrfToken"]}
        expense = c.post(
            "/api/expenses/commands/create",
            headers=headers,
            json={
                "requestKey": "restore-drill-expense",
                "description": "Restore drill",
                "amount": 25,
                "tax": 0,
            },
        ).json["record"]
        for action in ("submit", "approve", "pay"):
            response = c.post(
                "/api/expenses/commands/" + action,
                headers=headers,
                json={
                    "requestKey": "restore-drill-" + action,
                    "id": expense["id"],
                    "version": expense["version"],
                },
            )
            assert response.status_code == 200, response.json
            expense = response.json["record"]
        assert (
            expense["status"] == "Paid"
            and float(c.get("/api/finance/summary").json["balanceCheck"]) == 0
        )
        print(
            json.dumps(
                {
                    "tablesVerified": len(a),
                    "rowsVerified": sum(v[0] for v in a.values()),
                    "match": True,
                }
            )
        )
    else:
        raise ValueError("Use prepare or compare")


if __name__ == "__main__":
    main()
