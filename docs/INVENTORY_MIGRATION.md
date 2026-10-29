# Native Inventory — phase 5

Inventory (`erp.html?view=inventory`) and Stock Movements (`view=stock-moves`) now
use React/strict TypeScript in the existing shared shell. Products remain the shared
native product master. The converted routes use compact bootstrap and bounded SQL
resources, without aggregate app/HR reads or the legacy inventory renderer.

## Screens and operations

- Stock balances show name, SKU, unit, on-hand quantity, average cost and valuation.
  Search/filter stock goods, services or all products. Services have no stock actions.
- Dashboard totals use canonical relational balances: stock-product count, inventory
  value, movement count and the single warehouse `WH / Stock`. Currency stays PKR.
- Movement lists are paginated and searchable by product/SKU, movement number,
  operation and source; date and product filters are supported. Open one immutable
  movement for quantities, value, reason and authorized source/journal links.
- Stock Adjustment accepts a signed quantity. Positive quantities add inventory at
  the entered unit cost; negative quantities issue at current average cost.
- Scrap accepts a positive quantity to issue at current average cost. Adjustments
  and scrap post valuation against account 5105; inventory uses account 1200.
- Return Stock is available only for an unreturned purchase receipt or validated
  sales delivery. Partial returns are bounded by original unreturned quantity.
  Vendor returns issue at current average cost and require sufficient on-hand stock.
  Customer returns recover original delivery value, allocating its cents cumulatively
  so the final return clears the original cost exactly. Existing historical movements
  remain unchanged; new commands account for previous returns when calculating limits.
- Authorized users can export the current filtered movement page as CSV, with formula
  escaping. Source-print links require the source's view/export permissions and scope;
  journal links appear only for authorized accounting users.

Posted movements cannot be edited or deleted. Stock returns reverse stock and cost
postings; they do not create commercial credit notes, tax refunds or bank transfers.
Zero-cost movements can have no journal because they carry no financial value.
All existing sales, purchasing, manufacturing and expense posting services remain.

## API and concurrency

| Endpoint under `/api/inventory` | Purpose |
| --- | --- |
| `GET /summary` | SQL warehouse totals |
| `GET /products` | Paginated stock/service balances and selector choices |
| `GET /products/<id>` | One product balance and version |
| `GET /movements` | Paginated movement headers |
| `GET /movements/<id>` | Movement details, current return limit/version and authorized links |
| `GET /movements/export` | Current filtered page CSV |
| `POST /commands/{adjust|scrap|return}` | Validated atomic stock commands |

Lists default to 25 rows, maximum 100. Reads use canonical SQL tables rather than
materializing business registers or a per-product movement history. Stock reads
require Inventory view; commands additionally require Inventory approve. Export
requires Inventory export. Authorized inventory records remain company-wide for
this one-company/warehouse deployment; HR/CRM privacy rules are unchanged.

Commands allowlist fields and require an actor-scoped request key plus current
product/movement version. Versions include current balance and, for returns,
previous return quantities/values. Missing versions return 428; stale versions and
request-key collisions return 409. Permissions are checked before idempotent replay.
The shared transaction lock serializes writes. Stock balances, movements, journals,
command receipt/reason and audit all commit atomically. Repeated accepted requests
cannot duplicate stock or financial postings. Native commands use explicit creator
attribution and avoid reconstructing app/HR aggregates; existing creator sidecar
metadata is retained. Older ERP endpoints remain for unconverted modules and keep
their prior compatibility contract.

## Upgrade

Stop workers and back up the database first. Replace application files while keeping
`instance`, database/environment settings and the virtual environment. In Windows CMD,
from the project folder:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app run --host 127.0.0.1 --port 5000
```

`init-db` adds `inventory_command` for idempotency/reason metadata. Existing products,
balances, movements and journal/source IDs stay in their current tables; no ledger
rewrite or replay occurs. `migrate-storage` is safe to repeat and handles earlier
master/trade/HR releases if needed. Keep your existing administrator and do not
reseed. Compiled frontend assets are included; Node is unnecessary for desktop ZIP
users. Hard-refresh the browser after upgrading.

## Verification and limits

Native backend scenarios cover stock/ledger tie-outs, adjustments/scrap, insufficient
stock, invalid/service inputs, period locks, stale writes/idempotency, partial vendor
returns, exact customer-return cents, permissions, SQL reads/writes without aggregate
projection, filters/pagination/CSV and schema upgrade without reposting. DOM checks
exercise the shared navigation and native resource/read models. Chromium uses actual
adjustment/scrap/return forms, negative-stock errors, movement details/export and mobile
layouts with synthetic data.

This remains one warehouse with average costing. Lots/serials/expiry, FIFO, transfers
between warehouses, physical-count approval batches and commercial refund workflows
are separate work. Query/index and concurrency load testing remains necessary before
large-volume production claims. Manufacturing, Expenses and administration contents
remain the next UI conversion phases.
