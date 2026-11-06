# Query-local workflows and operational verification — phase 10

Native Sales/Purchasing and HR commands no longer project, copy or persist whole
company/HR registers. Existing React screens, URLs, role grants, account credentials
and economic history remain unchanged. The remaining native CRM lead/reminder scope
checks also load only referenced leads and permission configuration.

## Command behavior

Sales/Purchasing loads a SQL workflow graph around the selected document/source:
its workflow ancestors, linked sibling/child documents, required product/party
masters and source leads. Master/party references never expand into unrelated orders.
This preserves split receipt/billing/payment conservation, award selection, draft
reservations, parent completion and CRM synchronization while excluding unrelated
company records. Existing line calculations and ledger posting functions operate on
that graph. Only changed headers/lines and the affected lead are written; unrelated
records and register positions are not rewritten or deleted.

HR loads the selected record and its referenced employee/candidate/manpower rows.
Attendance/payroll period conflicts, overlapping live leave and open separations are
checked with SQL against the database, rather than loading everyone's history.
Historical label-only employee references still require unambiguous resolution;
ambiguous/missing references do not acquire invented employee links. Onboarding,
payroll posting/payment and separation/account revocation retain their existing
atomic behavior. Only changed HR rows are written.

A new `workflow_conflict_key` table supports indexed global document-number,
payment-reference, employee-number and candidate-onboarding conflict checks.
Normalization preserves the previous lower/casefold rules, including Unicode-safe
payment references and employee numbers. Legacy duplicates remain readable for
correction; native conflicting commands fail. A companion `workflow_legacy_link`
index preserves reverse traversal of historical unresolved trade links without
scanning JSON in every header. Native writes, compatibility imports/persistence and
controlled index rebuilding keep these derived rows synchronized. HR label/position
indexes support conflict lookups and native insertion ordering.

The shared ERP database lock still serializes economic mutations. After waiting for
the lock, native trade/HR commands refresh account/session/permission state so revoked
sessions and changed roles cannot authorize work from a stale request snapshot.
Current versions and actor-scoped receipts remain required. HR login retries verify
the supplied password against the linked account's current salted hash; credentials
never enter command fingerprints, public records or audit details.

Record changes, derived keys, command receipts, journals, stock, reconciliation,
CRM/employee effects and audit commit in one transaction. The document revision
increments without replacing stored configuration or reconstructing full registers.
Posting failure, stale versions or conflicts roll back the whole command.

## Upgrade and daily checks (Windows CMD)

Stop workers/server first and back up the existing database/`instance` directory.
Keep the current database, environment settings, users and login. Replace application
files with the latest `codex/database-backend` branch version. From the project root:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app workflow-health
python -m flask --app backend.app run --host 127.0.0.1 --port 5000
```

`init-db` creates/backfills the derived conflict/reference tables and supporting
indexes once. Storage migrations remain idempotent. Existing business IDs, custom
metadata, accounts and posted journals stay in place; historical postings are not
replayed. No new frontend build or Node installation is required for desktop testing.
Do not reseed or recreate Admin.

`workflow-health` is read-only. It reports index readiness, unbalanced/incomplete
posted journals, negative stock balances, duplicate conflict-key groups and known
historical unresolved trade links. The first four determine its health result/exit
status; unresolved legacy links are separately reported for review. A healthy result
is an operational check, not proof of statutory compliance or full client acceptance.

After a controlled direct SQL repair, derived indexes can be rebuilt explicitly:

```bat
python -m flask --app backend.app rebuild-workflow-indexes
python -m flask --app backend.app workflow-health
```

This rebuild changes derived lookup rows only, not business documents or journals.
Ordinary UI/API operations maintain the indexes automatically. Direct database
writes outside these services require operator review and index rebuilding.

## Executed verification

- Existing Sales/Purchasing and HR financial/permission/migration suites retain all
  earlier scenarios. The complete backend suite now has 128 tests.
- New tests prohibit business/HR aggregate projection during complete native purchase,
  Sales and payroll workflows, including shared CRM setup/scope checks.
- A locality fixture inserts 1,000 unrelated trade headers and 1,000 unrelated employees.
  Targeted trade/employee edits load none of those unrelated ORM records, preserve
  their counts and change only the requested rows. This is a locality check, not a
  throughput or maximum-capacity certification.
- Cross-order payment reference collisions and Unicode-insensitive employee IDs
  cannot bypass global conflict checks by being outside the selected graph.
- Two concurrent payroll creations for one employee/month yield one success and one
  conflict. Concurrent approvals yield one posted journal and one stale-version
  conflict. The global lock remains the concurrency mechanism.
- Index upgrade/rebuild tests retain business rows and journal identities. Health
  tests detect duplicate derived keys and verify rebuilding without business changes.
- SQLite recovery uses a database backup containing seeded inventory and posted/paid
  payroll, compares every table's row count/content digest, runs integrity/foreign-key
  checks, signs in to the restored database and verifies financial balance/history.
- PostgreSQL CI prepares an isolated source database with stock/journals/account data,
  performs `pg_dump`/`pg_restore` into a separate isolated database, compares every
  table's count/content digest, signs in and posts/reimburses an expense after restore.
  The drill refuses database names outside its dedicated CI source/restore names.
- All 50 shared screen/route checks and the full Chromium module simulations remain
  part of CI. Frontend behavior and compiled assets are unchanged by this phase.

## Practical boundaries

The workflow graph grows with the selected RFQ/order chain, not the whole company;
a very large single chain can still load many related documents. The ERP lock is
global, so writes are serialized across modules. This phase removes whole-register
command adapters; it does not claim high parallel write throughput or replace the
lock with row-level business-resource locking.

Explicit legacy transport, operational export/import, schema/data upgrades and
backup verification remain bulk operations. Larger single-workflow datasets,
representative multi-user throughput, hosting deployment, off-server backup retention,
restore timing and client acceptance still need environment-specific verification.
Existing one-company/one-warehouse limits and manual Pakistan statutory tax/payroll
treatment are unchanged. No deployment or merge is performed by these changes.
