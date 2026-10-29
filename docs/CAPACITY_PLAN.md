# Capacity engineering — phase 11

## Planning target, not a supported limit

Use a provisional first-client envelope of **100 named users, 25 simultaneous
active users, 10,000 products, 100,000 transaction headers and 1,000,000 lines over
five years**. Keep Pakistan/PKR, one company and one warehouse for this iteration.
These assumptions are engineering targets awaiting client confirmation, not tested
capacity or permission to advertise enterprise readiness. Named users, concurrent
sessions and active transactions are different measures.

Provisional acceptance criteria on an agreed production-sized PostgreSQL host:

- Common paginated reads: p95 under 1 second; ordinary writes: p95 under 2 seconds.
- No unexpected 5xx, lost updates, duplicate economic postings or conservation errors
  at the agreed steady workload. Expected stale-version conflicts are reported separately.
- Sustain the workload for 60 minutes and a double-load burst for 10 minutes without
  rising queues, unbounded memory growth or connection exhaustion.
- Complete a backup/restore drill with agreed recovery-time/data-loss objectives.
  Those objectives must be set by the client; no availability commitment is implied.

The targets must be measured with a representative Sales/Purchase/Inventory/HR/
Finance mix, employee roles, approvals, line counts and realistic think time. A count
of employees or empty documents does not substitute for realistic commercial history.

## Delivered baseline tool

`python -m backend.capacity_probe` creates a **fresh isolated database** and runs
synchronized independent Flask clients. It seeds synthetic historical employee and
purchase-request rows in bounded batches and creates a separate synthetic login
and employee per active client. Each iteration reads the paginated Purchase/HR
registers and Finance summary, then creates, approves and pays a payroll record.
Approval/payment retries use identical request keys to verify replay behavior.

The JSON report includes request counts, HTTP status counts, elapsed time, request
throughput, per-operation p50/p95/p99/maximum latency, SQL query counts and ERP
control UPDATE execution time. That UPDATE time **includes database execution and
lock waiting**; it is not an exact isolated lock-wait measurement. Login/password
hashing and fixture preparation occur outside timed traffic. Runtime, CPU count and
database type are recorded; no credentials, session cookies, database URL or personal
records are included.

The workload is closed-loop with no think time and one process using threads. It
exercises the real Flask middleware, sessions, SQL services and database connections,
but excludes HTTP sockets, TLS, proxies, Gunicorn multi-process behavior, browser
rendering and network latency. It is a diagnostic API-service baseline, not a load
certificate or a simulation of 25 complete human working sessions. Short runs and
small tail samples cannot establish reliable p99 or sustained capacity. Replayed
commands are counted in request throughput, not as new economic transactions.

Every case verifies all responses, completed workflows, exact paid-payroll count and
net total, exactly two new journals per workflow, balanced posted journals, stock
nonnegativity and derived-key health. Failures produce a nonzero exit status; timing
numbers are observations, not CI pass/fail gates on shared runners. Existing full
Sales/Purchase/manufacturing/expense and concurrent-conflict regressions remain in CI.

### Windows desktop baseline

From the project root with the existing virtual environment active:

```bat
python -m backend.capacity_probe --rows 1000 --workers 1 4 8 --iterations 5 --output capacity-report.json
```

With no `CAPACITY_DATABASE_URL`, the tool creates and removes its own temporary
SQLite database. It **ignores `DATABASE_URL`** and never modifies your running demo
or production database. The output report remains at the requested path.

### PostgreSQL baseline

Create a new empty database called `purchase_capacity_test` on a separate test
instance. Supply its connection URL through `CAPACITY_DATABASE_URL`, then run:

```bat
python -m backend.capacity_probe --rows 10000 --workers 1 4 8 25 --iterations 20 --output capacity-report.json
```

The variable must use SQLAlchemy's `postgresql+psycopg://` URL. Do not commit or paste
its password into reports. The tool refuses other PostgreSQL database names and any
existing tables. It never drops tables or databases. The isolated PostgreSQL database
is retained for investigation; run again with a newly created empty dedicated test
database. Synthetic users are Admin to isolate service/database contention; this
benchmark does not replace permission testing. CI runs a smaller 1,000-row 1/4/8-client
PostgreSQL case and prints the JSON report in the job log.

## Bounded contention handling

All ERP economic writes still acquire the shared control-row lock. PostgreSQL lock
acquisition now temporarily uses `ERP_LOCK_TIMEOUT_MS` (default 5000; range 1–60000).
The prior transaction-local PostgreSQL timeout is restored after acquisition. A lock
timeout or detected deadlock during acquisition rolls back the entire transaction
and returns HTTP 503 with `Retry-After: 1`, without SQL/connection details. SQLite
BUSY/LOCKED at the same acquisition boundary has the same response; its waiting
period remains controlled by SQLite's driver settings. Other SQL failures are not
misclassified as ordinary contention.

Clients should retry a busy command with the **same idempotency key and payload**
after a delay, then refetch on stale-version conflict. No automatic retry or sleep
is performed inside a database transaction. This bounds PostgreSQL waiting; it does
not increase parallel write throughput. The setting applies only while acquiring the
ERP lock, not to every query or the entire request deadline.

A two-connection regression holds the ERP row, confirms a real request returns 503
without creating an employee, then releases the lock and confirms the same request
key succeeds and replays as one record. This runs on SQLite and PostgreSQL.

## Safe route to concurrent writes

Do not delete the global lock based only on fast reads or a small benchmark. Replace
it incrementally with these prerequisites:

1. Inventory every write boundary, including legacy imports, account/role changes,
   stock, reconciliation, period close, number allocation and derived-key rebuilding.
2. Add a canonical database-enforced uniqueness strategy for document numbers,
   references, employee/date/month and onboarding, with explicit handling of existing
   historical duplicates. Current derived conflict indexes are not unique constraints.
3. Make sequence allocation atomic and independent of a shared global lock. Define
   consistent locking order for products, source-order lines, employee/month payroll,
   bank matching and fiscal-period controls; avoid deadlock cycles.
4. Decouple per-record changes from shared app/HR document revisions. Preserve exact
   source quantity/money conservation when simultaneous sibling documents change.
5. Convert one workflow at a time, running cross-process races for same and different
   resources, rollback injection, receipt replay, period close and account revocation.
6. Compare throughput/tails/lock waits before and after on the same PostgreSQL host,
   with a Gunicorn/proxy HTTP load test and representative historical lines/journals.
   Keep the global-lock path until the replacement passes economic invariants.

Background report/export jobs, independent read scaling and targeted report indexes
can follow measured bottlenecks. Multi-company/warehouse and statutory localization
remain separate business scope. No production deployment or enterprise-capacity
claim is made by this phase.

## Recorded development-host observation (28 October 2026)

The [raw SQLite report](benchmarks/capacity-sqlite-phase11.json) used 10,000 historical
employees and 10,000 historical purchase requests, five iterations per client:

| Concurrent clients | Completed payroll workflows | Requests/second | All-request p95 | Result |
| --- | --- | --- | --- | --- |
| 1 | 5 / 5 | 59.83 | 25.606 ms | Passed correctness checks |
| 4 | 20 / 20 | 51.759 | 212.064 ms | Passed correctness checks |
| 8 | 40 / 40 | 44.634 | 652.391 ms | Passed correctness checks |
| 25 | 120 / 125 | 46.021 | 1999.276 ms | Failed: five HTTP 503 busy responses |

The 25-client case had p99 9235.244 ms, including connection acquisition/service
queueing outside the ERP UPDATE. This short SQLite run is evidence of contention,
not an accepted 25-user production limit. Throughput does not improve with added
writers. All four cases retained healthy ledger/stock/key checks, but an incomplete
workflow is still an acceptance failure. No busy retries were hidden in these results.
Use PostgreSQL and deployed multi-process HTTP measurements for the next comparison;
do not extrapolate this host's absolute timings to client hardware or large companies.

Payroll now uses employee-level preparation plus a serialized financial posting tail;
see [phase 16](PAYROLL_CONCURRENCY.md). Recorded earlier SQLite results remain
historical observations. Rerun on the intended PostgreSQL host before capacity claims.
