# Native Manufacturing — phase 6

Manufacturing dashboard, Bills of Materials and Manufacturing Orders now use
React/strict TypeScript inside the existing `erp.html?view=manufacturing`, `boms`
and `production-orders` routes. Shared navigation, PKR, one company and WH / Stock
remain unchanged. Routes use compact bootstrap and paginated SQL resources, without
business/HR aggregates or the legacy manufacturing renderer.

## Flow

1. Create stock products in Products: a finished product and its raw components.
2. Open Manufacturing → Bills of Materials → New BoM. Select the finished product,
   batch output quantity, 1–100 distinct stock components and their quantities per
   batch. Enter an optional nonnegative conversion cost per batch.
3. View the BoM and choose Create Manufacturing Order, or use the dashboard/order
   button. New Manufacturing Order is disabled until at least one BoM exists, with
   a link explaining the prerequisite. Select a BoM, output quantity and production
   date; the form previews scaled component quantities and conversion cost.
4. The server copies the BoM quantities/cost into the order. View current material
   availability/shortages and estimated cost. Confirm the order, optionally Start
   Production, then Complete Production. Confirmation does not reserve inventory.
5. Completion consumes all components at current average cost, receives finished
   goods and posts the related journals in one transaction. Shortage or period-lock
   failure rolls back every movement, balance, journal and state change.
6. Inspect posted actual cost, Stock Movements and authorized Journal Entries.
   Authorized users can print the manufacturing order through Print / Save as PDF.

Only Draft orders can be cancelled. Confirmed orders can complete directly or pass
through In Progress, preserving the existing one-step workflow. Completed orders
and their economic snapshots are immutable. To change the source/quantity/date of
an unfinished draft, cancel it and create a new order.

BoMs can be edited with Manufacturing edit permission; output product identity is
fixed. Edits apply to future orders. Existing orders retain their component and
conversion-cost snapshots even when the current BoM name or recipe changes.

## Stock and accounting

Component issues debit WIP (1250) and credit inventory (1200). Conversion cost debits
WIP and credits Manufacturing Costs Accrued (2400). Finished goods debit inventory
and credit WIP for the full material-plus-conversion cost; WIP clears to zero.
Conversion accrual is not a supplier payment or settlement. The final cost comes from
actual stock movements, rather than the browser's preview. Zero-value movements may
carry no journal. The order's posting date follows the existing accounting period lock.

Availability and cost estimates are current views, not reservations or committed
posting values. Active-order versions include component balances; if stock changes,
reload details before an action. Preview calculations do not apply posting amount caps
prematurely, allowing large shortage plans to remain readable. Actual posting retains
the existing quantity/amount bounds and stock validation.

## APIs and permissions

Native resources are under `/api/production`:

| Endpoint | Purpose |
| --- | --- |
| `GET /summary` | SQL BoM count, order-state counts and completed output cost |
| `GET /products` | Bounded stock-product selectors |
| `GET /boms` | Paginated BoM headers/component counts; no component arrays |
| `GET /boms/<id>` | One versioned BoM and component requirements |
| `GET /orders` | Paginated order headers, state/date/search filters |
| `GET /orders/<id>` | One order snapshot, current availability, version and permitted actions |
| `GET /orders/<id>/print` | Authenticated escaped manufacturing order print layout |
| `POST /commands/<command>` | Atomic create/edit/action commands |

Commands: `bom`, `edit-bom`, `order`, `confirm`, `start`, `complete`, `cancel`.
Inputs are allowlisted. Each command requires an actor-scoped idempotency key; BoM
edits/order actions require current record versions, and order creation requires the
current BoM version. Stale records/source selections return 409; missing versions
return 428. Permissions are checked before replay. Successful retries cannot create
duplicate orders, consumption, output or accruals; conflicting key reuse returns 409.
The command receipt, audit, order, stock and journals commit atomically under the
shared transaction lock. Native and legacy completion endpoints share one posting
service, preserving source keys and costing rules.

Manufacturing view grants company-wide production access for this single warehouse.
Create, edit, approve and export permissions remain distinct. Product choice access
is limited to stock-product identity/units under Manufacturing permission. Financial
journals require Accounting view, inventory links require Inventory view, and print
requires Manufacturing export. Finance journal/Inventory movement source-print links
also enforce Manufacturing view/export. No role or ownership rewrite is performed.

Lists default to 25 rows and cap at 100. Header endpoints query SQL columns/counts
without loading every order or its component relationships. Detailed availability
is read only for one selected order. The older ERP API remains available for legacy
compatibility and retains its prior command contract.

## Upgrade an existing installation

Stop workers and back up the database first. Replace application files while keeping
`instance`, database/environment settings and the virtual environment. In Windows
Command Prompt, from the project folder:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app run --host 127.0.0.1 --port 5000
```

`init-db` adds `production_command`. Existing BoMs, order/component snapshots,
stock balances/movements, journal IDs and source keys remain in their original tables.
There is no ledger rewrite or replay. The storage migration is safe to repeat and
upgrades older master/trade/HR releases if necessary. Keep your existing login;
do not reseed or recreate the administrator. Compiled assets are included, so desktop
ZIP users do not need Node. Hard-refresh after upgrading.

## Verification and boundaries

Backend simulations independently verify component consumption, output valuation,
conversion accrual, WIP clearing, exact cents, retries, stale sources/stock, shortage
and locked-period rollback, immutable order snapshots after BoM edits, invalid/service
components, permissions, SQL pagination without aggregate loading, print escaping,
large shortage plans and schema upgrade without reposting. DOM checks cover shared
navigation and native production resources/read models. Chromium exercises actual
BoM creation/editing, BoM-to-order handoff, confirmation/start/completion, shortage
errors, cancellation, printing and mobile forms with synthetic data.

This is one-level, one-step, full-batch production. Work-center routing, scheduling,
capacity, partial consumption/output, backorders, subcontracting, by-products,
lot/serial traceability and reversal/unbuild workflows remain separate features.
Measured query/index, concurrency and deployment/load acceptance remain necessary
before large-scale production claims. Expenses and administration are the remaining
native content conversion phases.
