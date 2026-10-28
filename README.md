# Purchase — database-backed ERP

This is a general-products ERP demonstration for **Pakistan, PKR, one company and
one warehouse (`WH / Stock`)**. It integrates CRM, sales, purchasing, HR/payroll,
accounting, inventory, manufacturing and employee expenses. PostgreSQL is the
deployment target; SQLite supports local development and automated tests.

## Included

- CRM lead handoff, quotation approval, customer acceptance, sales orders,
  pending/delivered challans, customer invoices and full/partial payments.
- Purchase requests, approvals, RFQs, vendor quotations, comparison, purchase
  orders, partial receipts, partial vendor bills and payments.
- Relational double-entry journals and journal items, chart of accounts, manual
  journals/reversals, receivable/payable matching, bank/cash transfers, bank
  statement matching, period locks, general ledger, trial balance, P&L, balance
  sheet, open-item aging and cash-movement reporting.
- Relational stock balances and immutable movements, average-cost perpetual
  valuation, negative-stock prevention, adjustments, scrap and linked stock returns.
- Relational BoMs and manufacturing orders: Draft → Confirmed → In Progress → Done.
  Completion consumes components, accrues conversion costs and receives finished
  goods, with stock and journals committed in one database transaction.
- Relational employee expenses: Draft → Submitted → Approved → Paid, with optional
  PDF receipts and automatic expense/liability/reimbursement entries.
- HR employee records, attendance, leave, payroll and separation. Payroll approval
  posts salary expense and liabilities; payment clears salaries payable against
  Main Bank. Completing separation revokes linked non-administrator logins.
- Shared authenticated backend, hashed passwords, expiring HttpOnly sessions,
  CSRF checks, role permissions, department access with private CRM/HR scope, conflict detection and audit log.
- Fixed Pakistan/PKR setup. The separate Company Settings page is removed; basic
  company name/contact/NTN details are edited in an administrator profile dialog
  in the user dropdown. Product forms distinguish goods from services.
- Explicit demo opening data: raw materials, finished kit, standard BoM, bank/cash
  balances and opening stock. No demo data is loaded without clicking the button.
- Docker/PostgreSQL configuration, backup instructions, API tests and interface
  workflow checks. See [the client demo walkthrough](docs/DEMO_GUIDE.md).

## Frontend and storage migration

Customers, vendors, products, CRM leads/reminders, Sales, Purchasing, HR/payroll, Accounting/Finance, Inventory and Manufacturing now use
native React/TypeScript contents and record/action SQL APIs. Transaction headers,
source/product-linked lines and RFQ vendor relationships use relational tables. Existing databases must
run `init-db` and `migrate-storage` before using these screens. Expenses now uses native scoped claims, receipt upload, approval and reimbursement screens; administration contents remain later migration work. See [Expenses migration and upgrade](docs/EXPENSES_MIGRATION.md). See [Manufacturing migration](docs/MANUFACTURING_MIGRATION.md). See [Inventory migration](docs/INVENTORY_MIGRATION.md). See [Finance migration and upgrade](docs/FINANCE_MIGRATION.md). See [HR migration and upgrade](docs/HR_MIGRATION.md). See [upgrade instructions and exact scope](docs/FRONTEND_MIGRATION.md).

## Local setup (Python 3.12)

Run from the repository root:

```bash
python -m venv .venv
```

Activate `.venv` (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate`
on Linux/macOS), then:

```bash
python -m pip install -r backend/requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app create-admin
```

The administrator command prompts for name, email and a password of at least
12 characters. There are no default login credentials. `init-db` preserves
existing data and must run before starting workers.

For local HTTP development, disable the HTTPS-only cookie explicitly:

```bash
# Linux/macOS
COOKIE_SECURE=false python -m flask --app backend.app run --port 8000
```

```powershell
# Windows PowerShell
$env:COOKIE_SECURE="false"
python -m flask --app backend.app run --port 8000
```

Open `http://127.0.0.1:8000` and log in with the administrator you created.
The SQLite file is `instance/purchase.sqlite`; it must not be committed.
Do not use Flask's development server for a client deployment.

## VPS deployment with PostgreSQL and Docker Compose

One installation serves one company. Use a separate deployment and database for
each client; this version does not implement multi-tenant company isolation.

1. Copy `.env.example` to `.env`.
2. Generate a strong hex database password, for example with
   `python -c "import secrets; print(secrets.token_hex(32))"`, and set
   `POSTGRES_PASSWORD`. Hex avoids URL-escaping problems in `DATABASE_URL`.
3. Set `PUBLIC_ORIGIN` to the exact HTTPS origin, such as
   `https://erp.example.com` (no path). Keep `.env` private.
4. Initialize and create an administrator:

```bash
docker compose build
docker compose up -d db
docker compose run --rm web flask --app backend.app init-db
docker compose run --rm web flask --app backend.app migrate-storage
docker compose run --rm web flask --app backend.app create-admin
docker compose up -d web
```

5. Point your existing HTTPS reverse proxy at `127.0.0.1:8080`.
   `deploy/nginx.conf.example` contains the location block. Configure the domain
   and TLS certificate in your proxy. PostgreSQL is not exposed on a host port.
6. Verify sign-in, an actual save, a second browser reading the saved record,
   restricted-role access, and a backup/restore drill before client handover.

The database uses the named `purchase_db` volume. **Do not run
`docker compose down -v` unless you intend to erase the database.** A container
restart or ordinary `docker compose down` does not delete this named volume.

For a managed database instead of Compose, set `DATABASE_URL` to a PostgreSQL
connection URL. Both `postgresql://` and `postgresql+psycopg://` are supported.
Use the database provider's TLS settings when the connection crosses networks.

## Moving existing browser demo records

The database starts empty; browser data is never uploaded automatically.

As administrator, open **Import / Export Records** in the sidebar
(`admin-data.html`). On the same origin/browser as the previous demo, choose
**Import this browser's demo records**. Otherwise export from the old origin
using its browser console, then choose the resulting JSON file on the import page:

```js
const data = {
  app: JSON.parse(localStorage.getItem('purchase_demo_state_v1') || '{}'),
  hr: JSON.parse(localStorage.getItem('unified_hr_payroll_v1') || '{}')
};
const url = URL.createObjectURL(new Blob([JSON.stringify(data)], {type:'application/json'}));
const a = document.createElement('a');
a.href = url; a.download = 'purchase-demo-records.json'; a.click();
setTimeout(() => URL.revokeObjectURL(url), 1000);
```

Import is administrator-only and works only while both business and HR registers
are empty. Browser account passwords and role definitions are not trusted or
imported. Existing referenced user IDs are retained as **disabled accounts with
random password hashes**. Reset their passwords and activate them through User
Management. The first administrator retains ID `demo-admin` for compatibility
with existing ownership references. Review imported manager assignments.

Old attachments that contained only filenames cannot be recovered; upload the
actual PDFs. Invalid/duplicate legacy business records must be corrected before
import. An import is not a database backup restore.

## Backups and restore

The admin JSON export contains legacy operational/HR registers and sanitized user
profiles. It does **not** include the relational accounting, inventory, manufacturing,
expense or reconciliation tables, password hashes, sessions, audit history or PDF
contents. It is an operational-register export, not a complete ERP backup. Use PostgreSQL backups for a full recovery:

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U purchase -d purchase -Fc > backups/purchase.dump
```

Copy backups to private off-server storage. To restore into a deliberately chosen
empty/recovery database, stop the web service and run:

```bash
docker compose stop web
docker compose exec -T db pg_restore -U purchase -d purchase --clean --if-exists < backups/purchase.dump
docker compose up -d web
```

`--clean` replaces database objects. Verify the target and take a fresh backup
before restoring over an existing installation. Restores include sessions;
invalidate restored sessions before reopening to clients:

```bash
docker compose exec -T db psql -U purchase -d purchase -c 'DELETE FROM login_session;'
```

For SQLite development, stop the application before copying the database file.

## API

All paths below are prefixed with `/api`. Mutating authenticated requests require
the `X-CSRF-Token` returned by login or `/auth/me`; the browser sends the opaque
session cookie automatically. No tokens or credentials are stored in LocalStorage.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/auth/login` | Sign in and issue session cookie |
| GET | `/auth/me` | Current profile and CSRF token |
| POST | `/auth/logout` | Revoke current session |
| POST | `/auth/change-password` | Change password and revoke all user sessions |
| GET | `/state` | Permission-filtered business records and revision |
| PATCH | `/state` | Remaining compatibility collections/configuration; converted trade writes return 410 |
| GET/POST/PATCH | `/trade/:register[/:id]` | Scoped SQL transaction lists/details and native record commands |
| POST | `/trade/:register/:id/actions/:action` | Versioned approval/fulfilment/award actions |
| GET | `/trade/:register/:id/print` | Authenticated Print / Save as PDF layout |
| GET | `/hr/state` | Permission-filtered HR compatibility adapter; production PATCH returns 410 |
| GET/POST/PATCH | `/hr/records/<register>` | Scoped HR records and versioned workflow actions; see docs/HR_MIGRATION.md |
| GET/POST | `/users` | Administrator user listing / creation |
| PUT | `/users/:id` | Administrator account update |
| POST | `/users/:id/password` | Administrator reset, revoking sessions |
| POST | `/attachments` | Multipart PDF and `module` upload |
| GET | `/attachments/:id` | Permission-checked PDF download |
| GET | `/admin/export` | Administrator records export |
| POST | `/admin/import` | One-time import into empty registers |
| GET | `/admin/audit?before=123` | Administrator audit pagination |
| GET | `/health` | Database connectivity probe |

Save body example: `{"revision":3,"changes":{"vendors":[...]}}`.
Return codes include 401 (sign in), 403 (permission/CSRF), 409 (stale revision),
428 (revision missing), and 429 (failed-login limit).

ERP workspace endpoints share the same authentication/CSRF protections:

| Paths under `/api/erp` | Purpose |
| --- | --- |
| `/overview`, `/company-profile`, `/seed-demo` | Workspace, admin identity dialog and explicit opening data |
| `/accounts`, `/entries`, `/entries/:id/post`, `/entries/:id/reverse` | Chart and balanced manual journal workflow |
| `/reports`, `/aged`, `/reconcile`, `/period-lock` | Statements, open items, matching and accounting lock |
| `/transfers`, `/bank-statements`, `/bank-statements/:id/match` | Cash/bank transfers and statement matching |
| `/inventory`, `/inventory/adjust`, `/inventory/return` | Quantity/value ledger, adjustments and linked returns |
| `/boms`, `/manufacturing`, `/manufacturing/:id/:action` | BoMs and confirm/start/complete/cancel production |
| `/expenses`, `/expenses/:id/:action` | Claims and submit/approve/reject/pay workflow |

Creation requests use a unique `requestKey` (8–100 letters/numbers/hyphens/
underscores). Repeating a stock adjustment, manufacturing completion, expense
approval/payment or posting event cannot duplicate its ledger effects. Separate
mutations commit all corresponding stock and journal records atomically.

If a save fails, the red **NOT SAVED** notice blocks normal navigation. Reloading
server records discards the unsaved local edits. Re-enter those edits after
reloading. There is intentionally no automatic retry of stale business data.

## Tests

```bash
python -m pip install pytest
python -m pytest backend -q
npm ci
npm run test:dom
```

The DOM test starts its own HTTP server and isolated temporary SQLite database.
It exercises page scripts and actual saves; it is not a real-browser visual test.
GitHub Actions is configured for SQLite and PostgreSQL API tests, frontend syntax
checks and the DOM workflow suite. PostgreSQL tests use a disposable database
named `purchase_test`; never point `TEST_DATABASE_URL` at a live installation.

## Upgrading the earlier backend branch

Back up the database, stop web workers, deploy the new code, run `init-db`, then
restart workers. This release adds new tables without changing the existing
account/session/document columns. `init-db` creates these tables, seeds the chart
of accounts and adds missing ERP role permissions while retaining existing custom
permissions. It fixes the company country/currency to Pakistan/PKR.

Existing operational records are **not** silently backfilled into a historical
ledger. For client demonstrations, start with an empty installation and load the
explicit demo opening data. For an existing live database, a reviewed opening
balance/history migration is required before relying on financial reports.

## Implementation boundaries

This implements the connected **demo workflows**, not every Odoo feature or a
Pakistan statutory accounting/payroll localization. The workflows follow the
concepts documented in Odoo 18; this application does not embed or depend on Odoo.

- Accounts, journals/lines, reconciliations, stock balances/movements, BoMs,
  manufacturing orders/components, expenses and statement lines use relational
  tables. Customers/vendors/products, CRM leads/reminders and Sales/Purchasing
  headers/lines and HR/payroll records also use canonical SQL tables. Older CRM company/quote
  registers remain JSON. Native trade actions post into the relational ledgers atomically. A row lock serializes ledger/stock writes, and unique source
  keys prevent duplicate posting. This remains a small single-company demo design.
- Posted economic documents cannot be changed/deleted. Correct posted manual
  journals with reversing entries. Stock returns reverse quantities/valuation;
  commercial customer/vendor refunds require reviewed accounting credit entries.
- Manufacturing is one-step, one-level BoM production without work-center routing,
  capacity planning, subcontracting, by-products or lot/serial traceability.
  Conversion costs accrue to account 2400; settle actual costs through finance.
- Average costing is supported. Multi-warehouse transfers, FIFO, serial/expiry
  tracking and reservation planning are not implemented. Pending deliveries only
  allocate sales-order quantities; negative stock is checked at actual delivery.
- Partial purchase billing is bounded by unbilled accepted receipt value and the
  PO total. Automated landed-cost allocation and purchase-price variance handling
  are not included; shipping/additional charges need reviewed accounting treatment.
- Tax fields default to zero for demonstration. No rate is asserted to apply to
  every Pakistan product; FBR filings, withholding, EOBI/social security and
  statutory salary tax calculations are not implemented.
- Financial reports use posted journal items. Cash reporting is a signed cash
  movement summary including capital/internal transfers, not a statutory classified
  cash-flow statement. Aging uses current reconciliation state rather than a
  historical settlement snapshot.
- Bank reconciliation matches one statement line to one posted bank/cash journal
  item; automated bank feeds and split/combined statement matching are not included.
- RFQ/quotation “Send” records status; SMTP and payment gateways are not configured.
- Some historical operational lines/HR references retain product IDs, array positions
  or employee labels in compatibility projections. Query-local write validation and advanced migrations
  remain follow-up work. Future column changes require versioned schema migrations;
  `init-db` is not a general upgrade engine.
- Automated checks include DOM navigation/HR/production simulations and Chromium
  native Finance/master/CRM/Sales/Purchasing/HR forms, printing and mobile behavior. Production
  load/security acceptance and a PostgreSQL deployment smoke test remain necessary before handover. PDF uploads are not malware
  scanned and are served as downloads.

Reference flows:
- https://www.odoo.com/documentation/18.0/applications/finance/accounting.html
- https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp.html
- https://www.odoo.com/documentation/18.0/applications/finance/expenses.html

Authentication cookie settings follow Flask's security guidance:
https://flask.palletsprojects.com/en/stable/web-security/


### Department and record access

Operational records are shared with authorized departments; Finance sees company-wide
accounting. CRM leads remain restricted to their creator, assigned salesperson, relevant
manager and Admin. Sales records support team handoffs; HR/payroll and employee expense
claims retain their privacy rules. Creator identity remains immutable audit metadata.
See [Department access setup](docs/TEAM_ACCESS.md). Department policy needs no ownership rewrite; the storage upgrade requires `init-db` and `migrate-storage`, without reseeding.


### Frontend migration

The shared shell and Customers, Vendors, Products, CRM, Sales, Purchasing, HR, Accounting/Finance, Inventory and Manufacturing contents
use React/strict TypeScript. Converted screens use compact bootstrap, bounded resource
reads and versioned/idempotent record actions. Transaction totals, approvals, source
quantities, parent statuses and automatic postings are enforced on the server. Printing
uses authenticated browser Print / Save as PDF layouts. Compiled assets are included.

See [Sales/Purchasing phase and desktop upgrade](docs/TRADE_MIGRATION.md) and
[Frontend development and remaining scope](docs/FRONTEND_MIGRATION.md). Production
aggregate writes to converted trade/HR registers return 410. Native finance uses bounded SQL resources and versioned commands; the older ERP API remains a compatibility API. Large-scale readiness still
requires query-local validation/load testing; remaining module contents are later phases. See [HR phase details](docs/HR_MIGRATION.md).


Native Accounting/Finance phase: [workflows, reports, APIs and desktop upgrade](docs/FINANCE_MIGRATION.md). Finance permissions remain company-wide for authorized accounting staff.

Native Inventory phase: [stock workflows, APIs and upgrade](docs/INVENTORY_MIGRATION.md).

Native Manufacturing phase: [BoM, order, stock/accounting flow and upgrade](docs/MANUFACTURING_MIGRATION.md).
