# Payroll concurrency and financial safeguards — phase 16

Native payroll create/edit/approve/pay/replay now uses PostgreSQL resource locking.
Different employees can prepare payroll concurrently. One employee's payroll,
attendance and leave commands serialize on that employee's row; payroll month/date
edits run the existing global SQL duplicate check while holding that lock. Existing
payroll records also have a target-row lock, current-version check and actor/request-key
mutex. SQLite and `HR_RESOURCE_LOCKING=false` retain the global path.

This does **not** make journal posting fully parallel. Approval/payment use a short
transaction-wide PostgreSQL advisory mutex for their financial tail. It protects the
shared journal counter, creator registry and reconciliation state until commit or
rollback. It uses a two-integer advisory namespace separate from actor/key bigint
locks. Acquisition respects `ERP_LOCK_TIMEOUT_MS` and returns rollback/503 with
`Retry-After: 1` on recognized contention. Draft-only commands skip this mutex.

## Lock and write order

1. Shared ERP control-row gate, actor/request-key mutex, existing payroll target row.
2. Exclusive referenced employee row, then shared acting account and session locks.
   Historical labels resolve only when unambiguous; payroll actions already require
   a valid employee reference. Refresh permissions/session after waiting.
3. Existing salary calculations, immutable approved values, employee/month uniqueness,
   action permissions, version checks and changed payroll-row persistence.
4. For approval/payment, acquire the posting-tail mutex and refresh creator metadata.
   Use the same extracted payroll posting algorithm as the legacy/global adapter.
5. Post balanced salary/liability journals; payment posts Main Bank/net-pay entries
   and reconciles salary payable. Journal source and number columns remain database
   unique. PostgreSQL counter allocation now uses atomic INSERT ON CONFLICT UPDATE
   RETURNING for all prefixes, preserving the existing number format and counter value.
6. Update HR revision atomically only **after** the financial tail, then command receipt
   and audit. Commit payroll state, ledger, matches, creator attribution and receipt
   together. No shared HR revision lock is held while waiting for the posting mutex.

All other financial writers still take the exclusive ERP gate, which conflicts with
resource payroll's shared gate. Period close, offboarding, account/role changes and
manual reconciliation therefore cannot race a native payroll transaction. This gate
also freezes the accounting lock date while a resource journal checks the period.
Existing journal dates use the current Pakistan posting date; the payroll month is
not a retroactive accounting posting date. Zero-net payroll retains its existing
behavior: no bank journal or reconciliation is generated for a zero payment.

PostgreSQL's counter row and shared HR metadata still serialize transaction tails.
There is no throughput/capacity certification, independent parallel bank processing,
external bank transfer integration or statutory Pakistan payroll localization here.
Duplicate employee/month prevention uses the application lock protocol plus SQL
checks, retaining historical duplicates rather than adding a failing migration-wide
unique constraint. Direct SQL business writes outside the protocol remain unsupported.

## Payment and recovery behavior

Approval posts gross salary expense, deductions and net salary payable; payment
clears the whole net amount through Main Bank. If Accounting has already partially
or fully matched that payable externally, a new full payroll payment now stops for
Accounting review. It does not issue a second full bank payment. This phase does not
add partial payroll payments or automatically adopt an unrelated manual payment.

Replays use the same actor/key and payload and do not create another journal or
matching row. Distinct stale requests fail with 409. Locked periods fail without
partial payroll status, journals, numbering, matches or receipts; correct the period
through authorized Finance controls and retry. A failure after reconciliation also
rolls back the entire transaction. No automatic retry runs inside an open transaction.

## Verification and upgrade

The suite covers:

- Separate processes editing different employees' drafts, and separate processes
  synchronizing inside approval/payment validation before posting. Every workflow
  finishes Paid, creates exactly two balanced journals, retains the HR source creator,
  preserves all creator-registry entries and clears net salary payable exactly.
- Concurrent duplicate employee/month submissions and conflicting month edits.
- Same-key creation/replay, stale same-record edits, competing approval and payment
  requests, and exact-key replay without duplicate journals/reconciliation.
- Locked approval/payment with full-table digest equality after failure; injected
  failure after reconciliation with payroll, counter, registry, ledger, match, audit
  and receipt rollback; successful same-key retry after correction.
- Posting-mutex timeout, no partial approval and same-key retry after release.
- Native period close timing out behind in-flight payroll, then closing successfully
  and blocking a subsequent posting. Existing global/resource gate tests remain.
- External salary matching blocks another full payment without any table changes.
- Original access, net/gross/deduction, printing, migrations, private scopes and
  idempotency regressions plus PostgreSQL capacity and backup/restore drills.

Back up, replace application files and restart workers. No schema, numbering reset,
ledger rewrite, frontend build or reseeding is required. Normal init-db/migrate-storage
remain necessary if skipping earlier storage phases. Setting `HR_RESOURCE_LOCKING=false`
and restarting restores global HR locking; it retains the new shared posting algorithm,
atomic PostgreSQL counter allocation and external-matching payment safeguard.
