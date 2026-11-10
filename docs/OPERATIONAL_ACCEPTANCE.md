# Operational acceptance and recovery

## Results and boundaries

The November 6, 2026 local validation uses synthetic data with SQLite and an
isolated PostgreSQL 16.2 server. PostgreSQL runs over local TCP with Unix sockets
disabled. The full SQLite suite passed **230 tests**, with 25 PostgreSQL-specific
checks skipped. The PostgreSQL suite passed **254 tests**, with only the SQLite-specific backup
API test skipped. The PostgreSQL-specific multi-process/lock cases executed.
No production database or server was contacted. Docker orchestration, real HTTP
load, browser acceptance and live monitoring remain separate acceptance work.

- The recovery drill compared all 87 tables / 89 fixture rows, including binary
  attachment data and pending approvals, before making any writes to the restored
  database. After restore, the attachment downloaded byte-for-byte, self-approval
  was rejected, Finance approved the expense and payment independently, a repeated
  decision was rejected, and the ledger/stock/index health check passed.
- A separate acceptance test verifies a staff expense routes to its configured
  department manager within the manager's PKR limit, escalates to Finance above
  that limit, and still requires Finance authority for reimbursement. This is
  amount-based routing to one eligible reviewer, not consecutive multi-stage
  signatures. A department manager needs explicit Expenses approval permission.
- The approval-enabled service baseline retained 1,000 historical employees and
  1,000 purchase requests. Each client created/submitted an expense, requested
  independent approval and reimbursement, and attempted self/duplicate decisions.
  No unexpected request failures occurred; the expected 403 and 409 denials are
  included in latency measurements. Every paid expense produced exactly two
  balanced journal entries.

| Database | Concurrent clients | Completed workflows | Application calls | New journals | p95 call time |
| --- | --- | --- | --- | --- | --- |
| SQLite | 1 | 3 | 24 | 6 | 42.629 ms |
| SQLite | 4 | 12 | 96 | 24 | 224.278 ms |
| SQLite | 8 | 24 | 192 | 48 | 741.647 ms |
| PostgreSQL 16.2 | 1 | 3 | 24 | 6 | 80.179 ms |
| PostgreSQL 16.2 | 4 | 12 | 96 | 24 | 242.732 ms |
| PostgreSQL 16.2 | 8 | 24 | 192 | 48 | 484.064 ms |

These are short, closed-loop Flask test-client samples in one process. They omit
network, TLS, reverse proxy, multiple web processes, human review delays and
production-sized datasets. They do not establish supported users or sustained
HTTP throughput. Existing compatibility-mode payroll benchmarks remain separately
labeled; they are not approval-enabled measurements.

Raw local results: [SQLite approval baseline](benchmarks/approvals-sqlite.json),
[PostgreSQL approval baseline](benchmarks/approvals-postgres.json),
[SQLite recovery](benchmarks/recovery-sqlite.json),
[PostgreSQL recovery](benchmarks/recovery-postgres.json),
[PostgreSQL tests](benchmarks/postgres-tests.xml) and
[PostgreSQL validation summary](benchmarks/postgres-validation.json).

Both recovery drills passed, comparing all 87 tables / 89 synthetic fixture rows
before post-restore writes. PostgreSQL recovery used actual `pg_dump -Fc` and
`pg_restore --exit-on-error`, followed by the same attachment, approval and payment
checks. Neither a real customer database nor a real production backup was used.

## Run PostgreSQL 16 acceptance on Windows or Linux

Install/start Docker Desktop (Linux containers on Windows) or Docker Engine.
From the extracted project folder run:

```bat
python deploy/verify-postgres.py
```

The host needs only Python's standard library and Docker. The command starts
separate PostgreSQL 16 and Python test containers on a disposable network, with
no host database port or production volume attached. It copies source into the
test runner while excluding `.env`, local databases and output folders. It never
uses the application's existing database credentials. Test images/dependencies
must be downloadable the first time.

The runner executes the full PostgreSQL backend/concurrency suite, an
approval-enabled 1/4/8-client baseline, a real `pg_dump -Fc` / `pg_restore` drill,
and post-restore attachment/payment checks. It exits nonzero on failed checks.
Test containers, their anonymous data volumes and the test network are removed
on normal completion or handled errors. Inspect `summary.json` for cleanup
failures. A force-killed runner or host shutdown can require manual cleanup of
resources named `erp-verify-*`; do not remove unrelated containers or volumes.

Reports appear in `test-results/postgres-<run-id>/`:

- `summary.json`: stages, exit codes and cleanup result.
- `postgres-tests.xml`: actual PostgreSQL test outcomes, including skips.
- `capacity-report.json`: approval-enabled baseline and conservation assertions.
- `backup-report.json`: exact restore and post-recovery checks.
- `validation.log`: dependency, test and command output.

The local PostgreSQL suite, approval baseline and real custom-format dump/restore
all passed. A passing SQLite result must not substitute for PostgreSQL reports. The
standalone Docker runner has passed syntax/help/preflight checks locally, but its
Docker execution has not run in this environment because Docker is unavailable. The repository's
PostgreSQL CI job runs the same Python tests/probes and preserves reports; manual
workflow dispatch is enabled in the supplied workflow file after it is committed.
The GitHub branch was not updated by this work.

## Live monitoring and sustained HTTP acceptance

These steps require the deployed test server; they have not been configured or
executed against a live server here.

1. Configure an uptime check for `/api/health` through the actual HTTPS endpoint.
   It checks database connectivity; a 200 response does not establish ledger or
   approval health.
2. Run the read-only accounting/stock/index check against the intended deployment
   environment and retain its JSON and exit code:

   ```bat
   python -m flask --app backend.app workflow-health
   ```

   Investigate nonzero exits, unbalanced/incomplete posted journals, negative
   stock/value and duplicate workflow keys. Check the Pending Approvals inbox for
   unassigned/stale work separately; the health command does not validate routing
   authority, pending-review age or backup freshness.
3. Collect reverse-proxy/Gunicorn request duration, error rate and 5xx logs, plus
   database connection usage, lock waits, storage and backup age. Set alert
   thresholds to the expected workload and agreed response target. Redact secrets
   and personal data before sharing logs.
4. Exercise the deployed HTTP stack with realistic data and independent users for
   at least the expected busy interval. Include login/read traffic, approval
   requests/decisions, simultaneous payments and competing stock operations.
   Record p50/p95/p99, unexpected errors, completed workflows and ledger/stock
   conservation. Agree capacity targets before declaring acceptance.
5. Perform the production backup restore into a separate secured environment.
   This synthetic recovery drill does not validate your provider's schedule,
   retention, offsite copies, encryption or a real production backup. Include
   deployment configuration/secrets through your secure recovery process.

## Reproduce local checks

```bat
python -m pytest backend/test_approvals.py backend/test_backup_verify.py backend/test_approval_probe.py -q
python -m backend.approval_probe --rows 1000 --workers 1 4 8 --iterations 3 --output approval-report.json
```

The probe creates a temporary database when `CAPACITY_DATABASE_URL` is absent. If
provided, it must point to a fresh isolated `purchase_capacity_test` PostgreSQL
database or a fresh file named `capacity-probe.sqlite`. Existing schemas/files are
rejected. Recovery helpers similarly accept only dedicated source/restore names
and refuse a populated source. None of these commands is a production backup
scheduler or a reason to disable approval enforcement.
