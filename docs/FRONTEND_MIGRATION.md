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

Native trade and HR commands now load query-local workflow/employee records and write
only changed rows, retaining shared financial calculations/posting. CRM lead/reminder
scope checks also avoid aggregate projection. [Phase 10](QUERY_LOCAL_HARDENING.md)
covers derived conflict indexes, concurrent actions, backup/restore drills and remaining
single-workflow/throughput limits. Bulk adapters remain for explicit compatibility,
import/export and migration operations.
Full-page view navigation remains. Accessibility, document acceptance beyond the tested
print layouts, organization scopes and multicurrency remain separate work. This stage
alone does not establish large-scale production readiness.

## Repository cleanup

The workspace now has only two HTML entry files: `index.html` (login) and `erp.html` (all modules). Old module URLs redirect through the Flask frontend route, preserving query parameters, so bookmarks and menu links continue to work. Run the Flask backend rather than opening files directly.

`crm-workspace.js` starts the native customer and CRM screens. The superseded CRM, Sales, HR, ERP and import/export renderer scripts and duplicate redirect HTML files have been removed. Keep `app.js`, the workspace adapters, shared CSS, frontend source and `frontend-dist`: the current application still uses them. Tests, operational documentation and migrations remain maintained repository files. Docker builds regenerate frontend assets and exclude test sources and reports from the runtime context.

## Dashboard reference layouts

CRM, Sales and Purchasing now use the client reference composition again within the shared module navigation. CRM includes four KPIs, monthly expected-close opportunity values, the top five open PKR leads, stage counts, the current Pakistan-month follow-up calendar, quotation status counts and permission-filtered activity. All Time selects lead aggregates across all closing years; the chart shows the current year, or the selected closing year. Leads without an expected close date still count in All Time KPIs but cannot be plotted. Closed-won lead value is distinct from posted accounting revenue.

Sales/Purchase dashboards show the four KPI cards, six-month confirmed-order trend, workflow funnels, operational health, recent records and billing panels. The existing register totals remain in an expandable details section. Recorded order values include all statuses; trend values exclude drafts and cancelled orders. Collected/paid totals include Received/Processed payments, and outstanding amounts include posted/approved partly-paid invoices. Unavailable financial permissions display an em dash, rather than an invented zero. Summaries apply SQL visibility filters before aggregation and cap recent records and leaderboards at five.

Dashboard charts use responsive SVG coordinates and inline icons without chart/CDN dependencies. Shared dialog controls have consistent heights, normal-weight input text, checkbox sizing, grid spacing and disabled/focus styles. `tests/dashboard-browser.cjs` checks reference grids, chart rendering, year filtering, recent-record navigation and desktop/mobile bounds; `tests/forms-browser.cjs` checks control alignment and Cancel behavior throughout the migrated modules.

## Restricted financial figures

Sales Collected/Receivables and Purchase Payables/supplier payment figures now explicitly show **Unavailable** with **Requires invoice access** or **Requires payment access** when their register is restricted. The API continues to omit restricted registers, balances and recent invoice records, and direct resource requests return 403. This does not grant financial access to operational users.

An authorized zero is displayed as Rs 0.00. Missing or non-finite balance values are treated as unavailable data rather than converted to zero. Restricted recent-invoice panels explain the lack of access instead of claiming there are no invoices. Browser regressions cover a real Salesperson account on desktop/mobile, real API denial, authorized zero values and incomplete summary data.

## Unified module dashboards

All nine existing dashboard views now share `DashboardFrame`, KPI cards and panel components: ERP Overview, CRM, Sales, Purchasing, Accounting, Inventory, Manufacturing, Expenses and HR. The approved layout is four KPI cards, a two-panel main section and three lower panels. Every dashboard uses the same accent palette, typography, borders, rounded corners, tab styling and inline sidebar icons. At narrow widths the KPI grid has two columns and panel rows stack; very narrow screens use one KPI column.

`ModuleDashboard` composes the operational dashboards from existing permission-filtered summaries and bounded five-record endpoints. No database schema or write workflow changes are required. Financial values are posted ledger balances; production and HR charts are current status/register counts, expenses charts show claim amounts by status, and inventory charts explicitly show the current register page's top five stock-product values. These are not fabricated historical trends. Restricted or absent financial summary fields remain Unavailable, and genuine authorized zero balances remain zero.

CRM now uses four cards in one desktop row and the same rounded panels as Sales/Purchasing. Its chart and stage breakdown share the middle row; leaderboard, due follow-ups and quote summary share the lower row, with calendar and activity below. Existing search, register navigation, form actions, seed controls and Admin-only profile access remain in their existing authorized locations. Inventory retains its searchable balance register below the dashboard. Administration's Users/Roles, Activity and Data pages remain registers, rather than newly invented dashboard routes.

Validation includes all nine dashboards at desktop/mobile widths, empty states, consistent KPI/panel counts, card bounds, filters, recent-record links and a restricted user's Overview and financial KPIs. The existing 50-view HTTP/DOM and full browser workflow/form suites exercise the integrated screens.

## Accounting design implementation

Accounting now uses the approved dedicated dashboard: four posted financial KPIs, six-month income/expense chart, bank/cash reconciliation panel, customer invoice and vendor bill state summaries, financial report shortcuts and a bounded recent-document table. Recent rows distinguish document state from payment state. The Accounting submenu groups existing routes into Customers, Vendors, Accounting, Bank & Cash, Reporting and Configuration; role permissions filter its links. Company Profile remains in the Admin-only user menu.

The period selector supports This Month, This Quarter, This Year and All Time. Posted balance KPIs are cumulative as of the selected end date; profit uses the selected period. The chart displays six months through that end date. Invoice/bill counts and recent rows filter by document date and display their current settlement status. Status drilldowns preserve the selected date interval, including vendor Draft/Matched documents. Financial report shortcuts preserve the relevant period; aging includes older open items up to the end date.

`GET /api/finance/dashboard` requires Accounting view access. It aggregates posted ledger rows in SQL, reads document headers subject to their separate permissions and visibility, and returns no more than eight recent invoices/bills. Draft and future journal entries are excluded from the selected balances and trend. Bank unmatched totals come from actual unmatched statement lines. The existing direct bank/cash posting workflow remains in force: the screen uses Paid/Partially Paid states and labels unmatched bank receipts/payments explicitly. It does not invent separate outstanding-account balances or an In Payment state.

New Invoice/New Bill open existing transaction forms and retain their order/source requirements. Transfer, period lock, report selection, aged-account filtering and reconciliation actions use existing authorized commands. No schema migration is needed. Restart the Flask/Gunicorn backend after updating so the new read endpoint is registered, then hard-refresh the browser.


### Operational and accounting menu ownership

Sales now lists dashboard, customers, quotations, orders and products. Purchasing retains requests, RFQs, vendor quotations, comparison, orders, vendors and products. Customer invoices/payments and vendor bills/payments are accessed through Accounting; receipts and deliveries are accessed through Inventory. Existing order actions still create the linked documents with the same source references and backend permission checks. Existing URLs resolve to the owning module, including older bookmarked Sales/Purchase contexts. This is a navigation change, not a data migration or permission grant. Users with only invoice/bill/payment permissions can enter the corresponding Accounting register without access to ledger reports or the accounting dashboard.
