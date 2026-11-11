"""Run isolated PostgreSQL 16 checks with Docker; requires no host Python packages."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 4, 8])
    args = parser.parse_args()
    if (
        args.rows < 1
        or not 1 <= args.iterations <= 120
        or any(not 1 <= w <= 100 for w in args.workers)
    ):
        parser.error("Use rows >= 1, iterations 1..120, workers 1..100")
    if not shutil.which("docker"):
        parser.exit(
            2,
            "Docker is required. Start Docker Desktop, then run this command again.\n",
        )
    root = Path(__file__).resolve().parents[1]
    suffix = uuid.uuid4().hex[:12]
    network, postgres, worker = (
        "erp-verify-" + suffix + ending for ending in ("-net", "-db", "-runner")
    )
    reports = root / "test-results" / ("postgres-" + suffix)
    reports.mkdir(parents=True, exist_ok=False)
    report = {
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "postgresVersion": "16",
        "isolatedSyntheticData": True,
        "steps": [],
        "passed": False,
    }
    created = []

    def run(label, command, **kwargs):
        print(label, flush=True)
        with (reports / "validation.log").open("a", encoding="utf-8") as log:
            result = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, **kwargs
            )
        report["steps"].append({"step": label, "exitCode": result.returncode})
        if result.returncode:
            raise RuntimeError(label + " failed; see validation.log")

    def execute(label, *command):
        run(label, ["docker", "exec", "-w", "/work", worker, *command])

    try:
        run("Create disposable test network", ["docker", "network", "create", network])
        created.append(("network", network))
        run(
            "Start isolated PostgreSQL 16",
            [
                "docker",
                "run",
                "-d",
                "--name",
                postgres,
                "--network",
                network,
                "--network-alias",
                "db",
                "-e",
                "POSTGRES_USER=purchase",
                "-e",
                "POSTGRES_PASSWORD=isolated-test-password",
                "-e",
                "POSTGRES_DB=purchase_test",
                "postgres:16",
            ],
        )
        created.append(("container", postgres))
        for _ in range(60):
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    postgres,
                    "pg_isready",
                    "-U",
                    "purchase",
                    "-d",
                    "purchase_test",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("PostgreSQL readiness timed out")
        for database in (
            "purchase_capacity_test",
            "purchase_backup_source",
            "purchase_backup_restore",
        ):
            run(
                "Create " + database,
                ["docker", "exec", postgres, "createdb", "-U", "purchase", database],
            )
        env = []
        for key, database in (
            ("TEST_DATABASE_URL", "purchase_test"),
            ("CAPACITY_DATABASE_URL", "purchase_capacity_test"),
            ("BACKUP_SOURCE_URL", "purchase_backup_source"),
            ("BACKUP_RESTORE_URL", "purchase_backup_restore"),
        ):
            env += [
                "-e",
                key
                + "=postgresql+psycopg://purchase:isolated-test-password@db:5432/"
                + database,
            ]
        run(
            "Start disposable test runner",
            [
                "docker",
                "run",
                "-d",
                "--name",
                worker,
                "--network",
                network,
                "-v",
                str(root) + ":/source:ro",
                "-v",
                str(reports) + ":/reports",
                *env,
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
                "python:3.12-slim",
                "python",
                "-c",
                "import time; time.sleep(86400)",
            ],
        )
        created.append(("container", worker))
        run(
            "Copy source without local data or credentials",
            [
                "docker",
                "exec",
                worker,
                "python",
                "-c",
                "import shutil; shutil.copytree('/source','/work',ignore=shutil.ignore_patterns('.git','.env','.venv','node_modules','instance','test-results','__pycache__','.pytest_cache'))",
            ],
        )
        execute(
            "Install test dependencies",
            "python",
            "-m",
            "pip",
            "install",
            "-r",
            "backend/requirements.txt",
            "pytest",
        )
        execute(
            "Run PostgreSQL regression and concurrency tests",
            "python",
            "-m",
            "pytest",
            "backend",
            "-q",
            "-p",
            "no:cacheprovider",
            "--junitxml=/reports/postgres-tests.xml",
        )
        execute(
            "Measure approval-enabled service baseline",
            "python",
            "-m",
            "backend.approval_probe",
            "--rows",
            str(args.rows),
            "--workers",
            *map(str, args.workers),
            "--iterations",
            str(args.iterations),
            "--output",
            "/reports/capacity-report.json"
        )
        execute(
            "Prepare recovery source",
            "python",
            "-m",
            "backend.backup_verify",
            "prepare",
        )
        with tempfile.TemporaryDirectory(prefix="erp-recovery-") as directory:
            dump = Path(directory) / "synthetic.dump"
            with dump.open("wb") as output:
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        postgres,
                        "pg_dump",
                        "-U",
                        "purchase",
                        "-Fc",
                        "purchase_backup_source",
                    ],
                    stdout=output,
                    check=True,
                )
            with dump.open("rb") as source:
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        postgres,
                        "pg_restore",
                        "--exit-on-error",
                        "-U",
                        "purchase",
                        "-d",
                        "purchase_backup_restore",
                    ],
                    stdin=source,
                    check=True,
                )
        # A single JSON result is captured by the wrapper inside the container.
        execute(
            "Verify restored data, attachment and independent payments",
            "python",
            "-c",
            "import json,os; from backend.backup_verify import compare; "
            "result=compare(os.environ['BACKUP_SOURCE_URL'],os.environ['BACKUP_RESTORE_URL']); "
            "open('/reports/backup-report.json','w').write(json.dumps(result,indent=2)+'\\n')",
        )
        report["passed"] = True
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        cleanup = []
        for kind, name in reversed(created):
            command = (
                ["docker", "rm", "-f", "-v", name]
                if kind == "container"
                else ["docker", "network", "rm", name]
            )
            result = subprocess.run(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            cleanup.append({"resource": kind, "exitCode": result.returncode})
        report["cleanup"] = cleanup
        if any(item["exitCode"] for item in cleanup):
            report["passed"] = False
            report["cleanupRequired"] = True
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        (reports / "summary.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    print("Reports: " + str(reports))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
