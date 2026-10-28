# React and relational storage migration

## Implemented screens and storage

All screens use the React/strict TypeScript workspace shell (navigation, active tabs,
mobile menu and user dropdown). These module contents now use native React components:

| Screen | Read/write API | Canonical storage |
| --- | --- | --- |
| Customers (shared CRM/Sales) | `/api/customers` | `master_customer` |
| Vendors | `/api/vendors` | `master_vendor` |
| Products and services | `/api/products` | `master_product` |
| CRM leads | `/api/crm/leads` | `crm_lead` |
| CRM reminders | `/api/crm/reminders` | `crm_reminder` |
| CRM dashboard | `/api/crm/summary` | SQL totals from scoped leads/reminders |
| Sales and Purchasing transactions/dashboard/comparison | `/api/trade/…` | Domain headers, source/product-linked lines, RFQ vendor links |

Lists use SQL filtering/counting/offset/limit (25 rows by default, 100 maximum).
The dashboard queries grouped totals and at most 25 due reminders. CRM ownership
and assignment visibility is applied in SQL before counting/pagination/aggregation.
User-entered search wildcards are escaped and query values are bound parameters.
The assignee directory is searchable and bounded to 100 eligible active accounts.
Existing foreign-currency leads retain their currency and are excluded from PKR totals;
new native leads use PKR. No exchange-rate conversion is implied.
Reference selectors search bounded customer/lead lists instead of loading every record.

Writes update one SQL row, retain server-owned creator attribution and require a
record version for edits. Create requests are idempotent for an actor/resource/key.
All writes keep CSRF/session checks, permission checks, audit events and transaction
rollback. Editing the type of a product with stock history is rejected atomically.
CRM assignees are restricted on the server, customer/lead references are checked,
and quotation/won/lost stages are driven by Sales rather than manual CRM edits.
The Sales handoff continues through `erp.html?view=sales-quotations&leadId=…`.

Core master/CRM fields are typed SQL columns, money uses Numeric, search/ownership
columns are indexed, and per-record extension JSON retains legacy/custom attributes.
The migration preserves IDs, unknown attributes, optional field presence and numeric
reference types. It removes migrated master/CRM and Sales/Purchasing arrays from physical `document.data` JSON.
There is no dual-authoritative JSON copy of a migrated register. A compatibility
adapter reconstructs the old read model for unconverted screens and exports. Native
writes advance its document revision so stale legacy saves conflict rather than
silently overwrite newer records. Internal compatibility writes synchronize SQL rows atomically. Production aggregate transaction writes are retired (410).

## Upgrade an existing desktop installation (Windows CMD)

Stop the server and copy `instance\purchase.sqlite` to a backup location first.
Keep your existing `.env`, database and attachments. Extract the updated branch files
into the installation, including `frontend-dist` and all new backend modules. From
the repository root, with the existing virtual environment activated:

```bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
set COOKIE_SECURE=false
python -m flask --app backend.app run --port 8000
```

Open `http://127.0.0.1:8000`. Use your existing login. Do not reseed demo data or create
a second administrator. Node is unnecessary for desktop testing; compiled frontend
assets and third-party licenses are included.

`init-db` creates missing tables and preserves records. `migrate-storage` moves the
master/CRM and Sales/Purchasing registers in a transaction and verifies exact round trips before
committing. Repeating it makes no further changes. If a legacy value cannot fit the
new representation without changing it, migration stops and rolls back business
changes. Unmigrated installations receive a clear 503 message on native APIs rather
than an empty list that could be mistaken for lost data. Stop all workers during
migration; do not run migration concurrently with live writes.

For PostgreSQL/Docker, take a normal database backup and stop web workers, then run:

```text
docker compose run --rm web flask --app backend.app init-db
docker compose run --rm web flask --app backend.app migrate-storage
```

Fresh installations use relational registers from the start. No import or seed step
is required to activate the schema.

## Development and checks

Use Node 22+ at the repository root:

```text
npm ci
npm run build:frontend
npm run typecheck
npm run check:format
npm run test:dom
npx playwright install --with-deps chromium
npm run test:browser
python -m pytest backend -q
```

Start Flask separately; `npm run dev:frontend` watches/rebuilds assets. API requests
stay on the Flask origin, with HttpOnly sessions and the existing CSRF transport.
Credentials and business records are not persisted in browser storage.

CI checks SQLite and PostgreSQL behavior, migration/rollback, department/team privacy,
record conflicts, permissions, legacy compatibility, stock/journal invariants, shared
navigation, business simulations and real-browser native forms. It rebuilds the
production bundle and rejects stale tracked assets. Browser tests use synthetic
accounts and isolated temporary data; screenshots go to ignored `test-results`.
Set `PYTHON` to the virtual-environment executable when needed.

## Work still outstanding

Sales and Purchasing native screens, resource/action APIs, headers/lines and their
migration are now implemented. [Phase 2 details](TRADE_MIGRATION.md) describe workflows,
API boundaries, printing, permissions, migration preservation and verification.

HR/payroll now uses native React contents, record/action APIs and seven canonical SQL tables;
see [phase 3 and upgrade](HR_MIGRATION.md). Accounting/Finance now uses native screens with SQL reports, paginated resources and
versioned commands; see [phase 4](FINANCE_MIGRATION.md). Administration now uses native account/role/audit/import-export screens and an Admin-only company-profile dialog; see [phase 8](ADMINISTRATION_MIGRATION.md). Inventory now uses native stock balances/movements and versioned commands; see
[phase 5](INVENTORY_MIGRATION.md). Manufacturing now uses native BoM/order screens with snapshots, availability and
versioned actions; see [phase 6](MANUFACTURING_MIGRATION.md). Expenses now uses native scoped claims, receipts and versioned approval/reimbursement commands; see [phase 7](EXPENSES_MIGRATION.md). Overview and the older CRM company/quote registers now use native screens; the latter have two canonical SQL tables. See [phase 9](OVERVIEW_CRM_MIGRATION.md). Company/role configuration and creator attribution remain finite stored metadata.

Trade commands still reuse server-side cross-register compatibility validation/posting,
so further query-local validation/load testing is required for large data volumes.
Full-page view navigation remains. Accessibility, document acceptance beyond the tested
print layouts, organization scopes and multicurrency remain separate work. This stage
alone does not establish large-scale production readiness.
