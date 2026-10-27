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

Lists use SQL filtering/counting/offset/limit (25 rows by default, 100 maximum).
The dashboard queries grouped totals and at most 25 due reminders. CRM ownership
and assignment visibility is applied in SQL before counting/pagination/aggregation.
User-entered search wildcards are escaped and query values are bound parameters.
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
reference types. It removes these five arrays from the physical `document.data` JSON.
There is no dual-authoritative JSON copy of a migrated register. A compatibility
adapter reconstructs the old read model for unconverted screens and exports. Native
writes advance its document revision so stale legacy saves conflict rather than
silently overwrite newer records. Legacy writes synchronize SQL rows atomically.

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
five existing registers in a transaction and verifies exact round trips before
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

This commit does **not** complete the system-wide rewrite requested in the roadmap.
Purchasing transactions, Sales transactions, HR/payroll and administration still use
legacy module contents/aggregate transport; the unmigrated operational/HR registers
still live in versioned JSON. Accounting, stock, BoMs, manufacturing orders and
expenses already use relational backend services, but their screen contents still
need native React conversions. Legacy renderers remain behind an explicit HTML
compatibility boundary, and full-page view navigation remains.

Next conversions must move transaction headers/lines and HR records to domain tables
and resource/action APIs, convert their complete forms/workflow actions, and retire
aggregate endpoints only after Sales/Purchasing/payroll and posting simulations pass.
Company/role configuration and the creator sidecar also remain JSON metadata. The
current schema does not add database foreign keys from legacy transaction JSON to
master records; those references continue to use server validation.

Large-dataset/load testing, complete document/download/print acceptance, accessibility
review, organization scopes and multi-currency are separate outstanding work. This
migration stage alone is not a claim of large-scale production readiness.
