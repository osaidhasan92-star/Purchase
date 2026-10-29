# Resource concurrency — phases 12–14

## Converted non-economic HR workflows

Native **HR manpower requests, recruitment candidates and attendance** use
resource-level locking on PostgreSQL: create, edit, supported status actions and
command replay. These workflows create no stock, journals, payroll, employees or
login accounts. Candidate onboarding is still an explicit employee-create command
using the global economic lock. Employee changes, leave, payroll, offboarding and
Sales/Purchase/Inventory/Finance/Manufacturing mutations retain the global economic
write lock. SQLite retains the previous global path for all commands.

This is an incremental concurrency change, not a claim that economic writes now
scale in parallel or that the system is ready for large companies.

## PostgreSQL transaction order

1. Acquire `SELECT ... FOR SHARE` on the existing ERP control row. Multiple resource
   commands can share this gate; every existing global writer's UPDATE conflicts
   with it. Bulk HR and onboarding adapters, economic posting, role
   configuration and native administration remain excluded until the resource
   transaction finishes. No new lock table or migration is needed.
2. Acquire a transaction-scoped PostgreSQL advisory mutex derived from actor ID and
   request key. It serializes identical-key retries even before a receipt exists.
   The hash is a stable signed 64-bit SHA-256 prefix. A collision causes extra
   serialization, never permission expansion or loss of uniqueness.
3. For an existing request, lock its row `FOR UPDATE` and refresh its values. Stale
   version checks use this current record. Unrelated requests hold different row
   locks and can validate/write independently. For candidates, resolve the immutable
   manpower reference from that locked canonical record (including legacy unresolved
   metadata); new candidates use their submitted reference. Share-lock the referenced
   manpower row before validation. Two candidates can share one approved parent while
   a parent edit/approval waits. Missing/optional historical references retain their
   existing validation and transition behavior; no invented link is introduced.
   Attendance takes an **exclusive employee-row lock** instead of a shared parent
   lock, before its employee/date conflict query. Different employees can proceed
   together; the same employee's attendance commands serialize, even across dates.
   An existing record's employee reference is immutable. A legacy label-only record
   uses a bounded lookup and locks the employee only when exactly one match exists.
   Ambiguous/missing labels do not acquire a guessed foreign key and edits fail.
4. Share-lock the acting account and login session, then refresh/revalidate session,
   account and permission configuration. The account/session locks also coordinate
   legacy account and logout endpoints that do not take the ERP control lock.
5. Run the existing permission, scope, normalization, status and version checks.
   Persist changed records, command receipt and audit together. Manpower has no
   business number or cross-record uniqueness rule; candidates likewise have no
   unique-name/contact rule. Database primary keys and the request-key mutex protect
   identities and receipts. Attendance's SQL employee/date uniqueness check is
   protected by its exclusive employee lock across create and date edits. Legacy
   aggregate writers are excluded by the shared ERP gate. No new database unique
   constraint is introduced: historical duplicates remain preserved and direct SQL
   writers outside this protocol are not supported. Unchanged parents are not rewritten.
6. Atomically increment `hr` document revision with `revision = revision + 1`.
   This keeps legacy revision semantics without a stale whole-document compare and
   swap. The metadata row still serializes a brief final portion of each commit;
   this phase does not eliminate all shared rows.
7. Commit, releasing all row/advisory locks. Replayed commands return the stored
   record without changing the revision or writing another receipt/audit.

Resource commands deliberately bypass the legacy HR economic synchronization adapter,
which reacquires an exclusive ERP lock. Only the allowlisted manpower/candidate/attendance paths
do so; their state has no posting or offboarding effects. Candidate stage actions do
not fabricate employees. The employee-create/onboarding path remains globally locked,
so it cannot read an offer while a candidate rejection changes it. If rejection wins,
onboarding fails; if onboarding wins, the candidate is Hired and rejection is unavailable.
Extending resource locking to payroll, employees, leave or stock requires separate
invariant and lock-order analysis.

ERP lock waiting, target/parent-row locks, account/session locks and advisory-mutex waits
use `ERP_LOCK_TIMEOUT_MS` during acquisition (default 5000ms). The prior PostgreSQL
transaction timeout is restored afterward. Recognized timeout/deadlock failures roll
back and return 503 with `Retry-After: 1`; versions and same-key retry semantics remain.
There is no sleeping or automatic retry inside a transaction.

## Upgrade and rollback

Back up the database, replace application files and restart workers. This phase adds
no schema or ledger migration. Standard `init-db`/`migrate-storage` remain safe for
installations upgrading across earlier phases. Do not reseed existing installations.
The frontend and compiled assets are unchanged.

`HR_RESOURCE_LOCKING=true` is the default. Set `HR_RESOURCE_LOCKING=false` in the
environment and restart all workers to restore the original global manpower/candidate/attendance paths.
The Compose configuration passes this setting through. It does not change stored
business data or undo previous valid commands. Keep all workers on the same release
and use the normal stopped-worker upgrade procedure for predictable deployment.

## Verification

The regression suite includes:

- Two **separate spawned processes**, each with its own Flask application, pool,
  session and connection, editing distinct manpower requests, distinct candidates,
  or attendance for different employees. Candidates share one approved manpower
  parent; attendance uses distinct employee parents. A synchronization barrier inside
  validation can complete only if both commands have reached that point while holding
  their locks. Both succeed; HR revision increases by two, the global ERP revision
  stays unchanged and no journal is created.
- Concurrent identical-key creates return one identity and one stored record for
  each resource. Concurrent edits of the same version yield one success and one 409
  conflict. All three resources also have rollback and global-fallback coverage.
- A global exclusive writer blocks a resource command, and a resource shared gate
  blocks a global writer; bounded waits return 503 without partial records.
- An injected failure after row persistence rolls back the record, revision and
  receipt. The same key can subsequently succeed. Missing targets return 404.
- Disabling the feature exercises the existing global path. Existing HR recruitment,
  onboarding, access, payroll, offboarding and financial regressions remain required.

A parent-row lock test makes candidate creation time out with no partial candidate,
then confirms same-key success/replay after release. Rejection racing onboarding must
leave exactly one valid outcome: Hired plus one employee, or Rejected plus no employee.

Attendance races for one employee/date yield one success and one 409. Moving another
record onto an occupied date also fails without changing that record. An employee-row
lock test verifies bounded wait, no partial attendance and same-key retry/replay after
release. Legacy tests cover both unambiguous label conversion and rejection of
ambiguous labels without inventing a foreign key.

Nine PostgreSQL-specific cases skip on SQLite and run in PostgreSQL CI. The fallback,
failure, duplicate/date-edit, legacy-label and onboarding-race regressions run on both
databases. A successful two-process
rendezvous proves overlap and correctness at that boundary; it does not measure
sustained HTTP throughput or demonstrate that 25 production users are supported.

## Remaining work

Measure deployed multi-process HTTP traffic on a representative PostgreSQL host.
Then convert the next workflow with its required database uniqueness and consistent
resource lock order. Payroll/stock/period-close/reconciliation and source-line
conservation must keep their existing exclusive lock until their replacements are
explicitly tested. The phase-11 SQLite 25-client failure remains a valid recorded
observation; these non-economic HR changes do not resolve the payroll bottleneck.
