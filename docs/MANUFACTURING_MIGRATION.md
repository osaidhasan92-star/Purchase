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
   availability/shortages and estimated cost. Confirm to reserve available components.
   Use Check Availability after replenishment. Stage Materials moves the order's
   reserved Stock quantities to Production without changing value or posting journals.
   Optionally Start Production, then choose Complete Production to record actuals.
5. Enter finished quantity, actual consumed materials, separate component scrap and
   actual conversion cost. The form defaults to proportional planned quantities.
   Completing less than the order quantity closes this order for the produced quantity
   and creates a linked Confirmed manufacturing backorder for the remaining output
   and proportional planned materials/cost. Both records retain origin links.
   Consumption, scrap, output, accounting and backorder creation commit together.
   Shortage or period-lock failure rolls back every movement and state change.
6. Inspect posted actual cost, Stock Movements and authorized Journal Entries.
   Authorized users can print the manufacturing order through Print / Save as PDF.

Unfinished Draft, Confirmed and In Progress orders can be cancelled, releasing all
allocations. Already staged physical materials remain in Production until transferred
or allocated to another order. Confirmed orders can complete directly or pass
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

Reservations are per order, component and Stock/Production location. Sales orders,
other manufacturing orders, scrap and generic transfers cannot use these allocations.
Completion can use its own allocations plus free eligible materials for actual overuse;
it never uses another order's allocation or quarantined Returns. Check Availability
refreshes assignment explicitly; incoming receipts do not reassign waiting orders.

Component scrap debits Inventory Adjustment/Loss (5105) and credits inventory; it is
excluded from finished-goods value. Consumption debits WIP, and the recorded actual
conversion cost accrues through 2400. Material and conversion cost enter output
inventory and clear WIP. Planned conversion cost for a backorder is the original plan
less the proportional planned cost, independent of actual cost variance. Recorded
plans, consumption, scrap and remainder links appear in details and print layouts.

Availability and cost estimates remain current views rather than committed posting
values. Active-order versions include balances and allocations; if stock changes,
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

Commands: `bom`, `edit-bom`, `order`, `confirm`, `reserve`, `stage`, `start`,
`complete`, `cancel`. Manufacturing approval permission authorizes allocation,
staging, cancellation and completion. Stage Materials is the manufacturing-specific
transfer of this order's own allocated stock; generic warehouse transfers retain
Inventory creation/approval permissions.

Completion accepts optional `producedQuantity`, `conversionCost` and `components`
containing exactly every original `productId` with nonnegative `quantity` (consumed)
and `scrap`. At least one consumed material must be positive. Omitted actuals retain
full planned-completion defaults for older clients. Extra/duplicate component IDs,
negative amounts and output above the order remainder are rejected.
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

This release requires `migrate-storage` to add `material_reservation` and
`production_result`, then allocate available materials for historical active orders
oldest first (after existing Sales reservations). Repeat upgrades retain allocations
and do not repost completed orders. `init-db` also creates these tables and the existing
`production_command`. Existing BoMs, order/component snapshots,
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

This is one-level, one-step production with actual component consumption, component
scrap and partial-output backorders. Work-center routing, scheduling, capacity,
finished-output scrap, subcontracting, by-products,
lot/serial traceability and reversal/unbuild workflows remain separate features.
Measured query/index, concurrency and deployment/load acceptance remain necessary
before large-scale production claims.
