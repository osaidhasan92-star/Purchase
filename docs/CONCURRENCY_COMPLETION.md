# Operational concurrency completion — phase 17

This implements the agreed native Inventory, Sales/Purchase, Manufacturing, Expenses
and Finance concurrency scope on PostgreSQL. It builds on the completed HR/payroll
resource protocol. This is a correctness/concurrency delivery, not production-capacity
certification. One company, PKR and one warehouse remain unchanged.

## Completion checklist

| Area | Implemented behavior | Automated evidence |
| --- | --- | --- |
| Shared foundation | Shared ERP compatibility gate, actor/session revalidation, actor/key mutex, ordered resource locks, bounded waits | Existing global/resource exclusion and timeout tests; all native module paths use the same gate |
| Database safeguards | Database-primary-key normalized reservations for document numbers, payment references, employee numbers and onboarding; atomic PostgreSQL numbering | Reservation PK conflict and duplicate-history backfill; existing Unicode/reference/number regressions |
| Inventory | Product locks cover valuation, negative-stock checks, scrap/adjustment and return conservation | Independent-product process rendezvous; competing scrap and shared manufacturing consumption |
| Sales/Purchase | Lock the selected connected workflow/lead identities, refresh the graph after waiting, then lock its products before mutation | Independent request/quotation process rendezvous; receipt and delivery reservation races; existing split billing/payment/rounding simulations |
| Manufacturing | Lock BoM/order identity and all output/component products in sorted order | Independent completion process rendezvous; two orders competing for raw stock; cross-module stock consumption |
| Expenses | Per-claim state/version/idempotency protection; shared financial tail for reimbursement | Independent submissions across processes; two payment requests create one reimbursement |
| Finance | Shared compatibility gate plus serialized ledger/matching section for drafts, posting, transfers, matching and reversals | Independent callers reach the financial gate; reconciliation/reversal races and existing Finance regressions |
| Combined activity | Stock products use identical lock keys across Inventory, Trade and Production; payroll shares the posting mutex | Payroll/stock process rendezvous and competing Inventory/manufacturing consumption |
| Rollback and deployment switch | SQLite/disabled resource mode retains exclusive legacy path; period close remains exclusive | Existing cross-process HR/payroll, period-lock, failure injection, recovery and compatibility tests remain required |

“Independent” means operations without overlapping workflow/product/employee resources.
Product locks are conservative, including products referenced by a trade graph.
Creation/number allocation and shared financial work can still serialize; there is no
claim that every different document runs fully in parallel.

## Lock order and transaction boundaries

1. PostgreSQL native commands acquire a shared lock on ERPControl. All legacy/bulk,
   configuration, master-data and period-close writers retain their exclusive UPDATE
   lock, so they cannot race the converted writers. Account/session state is refreshed
   and permissions are rechecked after waiting.
2. An actor/request-key transaction mutex protects receipts before any record exists.
3. Acquire stable resource identities in deterministic order: connected trade nodes/
   source lead, inventory return movement, manufacturing BoM/order or expense claim.
   Trade parent/partner links remain immutable. Discovery is repeated after waiting;
   ancestor locks protect newly inserted siblings that were absent on first discovery.
4. Lock every involved product in sorted order before stock/version checks and any
   numbering or financial posting. All converted stock writers use identical keys.
   PostgreSQL advisory keys use a stable 64-bit hash; collisions can cause extra
   contention, and recognized deadlocks/timeouts return rollback/503 rather than
   permitting unchecked writes.
5. Acquire the existing transaction-wide financial posting mutex before shared
   numbering, unique-token reservation, creator metadata, journal/reconciliation work.
   Finance commands serialize this common section. No financial mutex holder later
   acquires another workflow/product lock. HR/payroll retain their reviewed employee
   order, and payroll posts before its brief HR revision-row update.
6. Persist records, stock, balanced journals, matches, reservations, receipts and audit
   in one transaction. Native trade increments App revision atomically after posting
   and returns the actual new revision, preserving legacy revision conflict semantics.

ERP.lock called inside the reviewed resource path acquires the posting mutex instead
of trying to upgrade its shared compatibility lock. Legacy callers still acquire
ERPControl exclusively. This avoids shared-to-exclusive upgrade deadlocks while keeping
unconverted paths safe. The common posting mutex is intentionally retained: journal
number counters and the existing creator registry are shared mutable resources.

## Database migration and historical duplicates

A new `workflow_reservation` table has primary key `(domain, kind, token)`. Tokens use
the existing lower/casefold rules and vendor partition for bill numbers. One owner
record can reserve a normalized token. Existing duplicate token groups retain every
business record and receive a NULL owner, explicitly blocking reuse until reviewed.
No duplicate is silently renamed, deleted, merged or reposted.

The idempotent `workflow_reservations` version-1 marker records successful backfill.
`init-db` creates the table and backfills existing derived keys; controlled index
rebuilding reconstructs both keys and reservations. Native writes maintain the two
representations atomically. The health CLI now reports `uniqueReservationsReady`.
Employee/date/month and leave ranges still use the reviewed employee lock + SQL
validation protocol; no destructive uniqueness/exclusion constraint is imposed on
potentially ambiguous legacy HR history. Direct business SQL writes outside the
protocol remain unsupported and require controlled repair/index rebuilding.

This is an explicit migration for the new table/data version, not a general-purpose
future column-migration engine. Later schema changes still need reviewed migrations.

## Upgrade an existing Windows installation

Stop all application workers first and back up the database, environment and attachments.
Keep the existing database/login. Replace application files, then from the project root:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app workflow-health
python -m flask --app backend.app run --host 127.0.0.1 --port 5000
```

Do not reseed. Resolve reported historical duplicate conflicts before production
acceptance. Node/frontend rebuilding is unnecessary for desktop testing.

`RESOURCE_CONCURRENCY=true` enables the newly converted native module paths on
PostgreSQL. Set it to false and restart workers to restore their exclusive ERP path.
`HR_RESOURCE_LOCKING` separately controls the previously converted HR/payroll paths;
set both false for fully exclusive operational writes. Retain the reservation table
and current code when switching modes; mode rollback does not undo business history
or remove the database safeguards. `ERP_LOCK_TIMEOUT_MS` continues to bound lock
acquisition; HTTP 503 includes `Retry-After: 1`. Retry the same command key/payload
outside a database transaction, and reload on stale-version conflict.

## Remaining readiness work

Period close, administration, master data and explicit bulk adapters remain exclusive
by design. Shared financial posting, numbering and creator metadata still serialize
parts of transactions. Representative mixed-module HTTP load tests are the next
measurement step; these concurrency rendezvous/race tests do not establish a user
capacity. Monitoring, off-server backup scheduling/retention, MFA/approval controls,
required business extensions, statutory validation and client acceptance remain on
the broader readiness roadmap. Nothing here merges or deploys the draft branch.
