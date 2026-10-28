# Native Overview and remaining CRM registers — phase 9

ERP Overview (`erp.html?view=overview`), CRM Companies (`view=companies`) and the
CRM Quote Register (`view=crm-quotes`) now use React/strict TypeScript in the shared
workspace. CRM submenus expose the two registers only when the user already has
Companies / crmQuotes view grants. Existing role grants are not silently broadened.
No blue dashboard hero, Refresh control or Company profile page is added.

## Overview

The overview links to authorized module workspaces. Financial cards require
Accounting view and use SQL totals through today's Pakistan date, matching the
Finance summary. Stock valuation uses current canonical stock balances; open
production is a SQL state count. Pending claims use Expenses view plus the existing
owner/direct-manager/Admin/Finance scope. Missing grants omit the corresponding
figures entirely. Users can open permitted module links without receiving financial
or private HR/register data. Normal page loads use compact bootstrap and bounded
resources, without fetching `/api/state`, `/api/hr/state` or `/api/erp/overview`.

Admin sees Load demo opening data only when the operational registers and ledger
are empty. The server rechecks under its write lock and rejects seeding if customers,
vendors, CRM records, products, trade documents, claims, stock or journals already
exist. This prevents the historical demo action from replacing existing master data.
Demo setup remains explicit and uses the established posting service; it is not an
automatic migration step or production opening-balance import.

## CRM directory and quote tracking

- Companies retains the old company/prospect directory with name, industry, contact,
  email, telephone and Active/Inactive status. It is shared with authorized CRM users.
  It does not replace the shared CRM/Sales Customers master or create customers.
- The CRM Quote Register retains the older amount-only tracking records, dates,
  currency and Draft/Sent/Accepted/Rejected/Expired status. It does not contain Sales
  product lines and is not the approved commercial quotation ledger.
- New tracking quotes require a visible lead, positive amount and PKR. Historical
  currencies can be retained when editing; no exchange-rate conversion is implied.
  Valid-until dates cannot precede quote dates. References and numbers are server-owned.
- Quotes remain private to creator/explicit historical owner, their direct managers
  and Admin. View/create/edit grants are also required. Scope is applied in SQL
  before search, pagination and detail lookup. Unknown historical creators remain
  Admin-only unless historical owner metadata already permits access.
- Status changes in this tracking register do not send email, change lead outcome,
  create orders/invoices, consume stock or post journals. Use Sales Quotations for
  the established approval → customer acceptance → order → delivery → invoice flow.
- Quote details offer Create Sales Quotation from Lead only when the source lead is
  accessible and the user has Leads view and Sales Quotation create grants. The link
  opens the existing Sales draft form; the user still selects product lines and saves
  explicitly. It does not copy an amount-only historical quote into a posted document.
- Company renames do not rewrite historical lead/quote snapshots. Historical missing
  lead references remain readable; editing requires selecting an accessible lead.

## Storage and upgrade behavior

Two canonical SQL tables, `crm_company` and `crm_tracking_quote`, replace whole
Companies/crmQuotes arrays. Indexed header fields support names, statuses, dates,
lead identities and creator/owner privacy. Per-row extension JSON preserves exact
field presence, original ID/amount types, nulls, historical currency, custom metadata
and unresolved old references. No fabricated FK or ownership is assigned to old data.

`migrate-storage` recognizes the new `_relationalCRMRegisters` marker even when the
previous master/trade migration has already run. It validates exact round trips
before removing the original arrays and commits atomically with the established
migration. Invalid legacy money stops migration without discarding source records.
Repeating migration is a no-op. No stock/journal records are replayed. The existing
legacy read/export/import adapters reconstruct these registers from SQL when an
explicit compatibility workflow needs them.

`crm_register_command` stores actor-scoped request receipts. Native creates/edits
allowlist fields, control creator/numbering on the server, require unique request
keys and serialize with the ERP lock. Reusing a key with different inputs returns
409. Edits require a current version (missing 428, stale 409). Record, receipt and
audit commit together. Native reads/writes never project business/HR aggregates.
Historical aggregate write endpoints keep their previous compatibility contract.

| Native resource | Purpose |
| --- | --- |
| `GET /api/overview/summary` | Permission-filtered SQL overview cards and seed eligibility |
| `GET /api/crm-registers/companies` | Shared authorized directory, SQL search/status/pagination |
| `GET /api/crm-registers/crmQuotes` | Private quote headers, SQL search/status/pagination |
| `GET /api/crm-registers/<register>/<id>` | One versioned record and permitted Sales handoff |
| `POST /api/crm-registers/<register>` | Idempotent creation |
| `PATCH /api/crm-registers/<register>/<id>` | Versioned/idempotent edit |
| `GET /api/crm-registers/lead-options` | Bounded visible lead choices |

Lists use 25 records by default and at most 100. Search wildcards are escaped.
Existing session/CSRF/origin controls apply. No credential storage is introduced.

## Windows upgrade

Stop the server and back up the database/`instance` directory first. Keep the current
database, environment and login. Extract the updated `codex/database-backend` branch
files into the actual project root, then run in CMD:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app run --host 127.0.0.1 --port 5000
```

Do not reseed or recreate Admin. `init-db` creates the new tables; `migrate-storage`
moves historical company/quote arrays after exact validation. Built frontend files
are included; desktop testing needs no Node installation. Hard-refresh the browser.

## Demonstration and verification

Open Overview and follow a permitted module card. Under CRM, create/edit a Company;
open Quote Register, choose a visible Lead and create a PKR tracking quote. Change
its tracking status, inspect the explanatory note and use the separate Sales handoff
when authorized. Test another account and its direct manager to verify quote privacy.

Seven backend scenarios independently cover historical round trips, rollback,
private quote/lead scope, status changes without economic effects, versions/replay,
validation, SQL pagination, permission-filtered financial totals, safe demo seeding
and native operations without aggregate projections. Shared route checks now cover
50 screens. Chromium exercises the real company/quote forms, edits, Sales handoff,
filters, Overview links, balanced ledger and mobile dialog alongside earlier flows.

The next substantial work remains replacing internal trade/HR aggregate validation
adapters with query-local services, followed by measured concurrency/load, full
backup/restore and client acceptance testing. This phase completes the remaining
requested screen conversion; it does not establish large-scale production readiness.
