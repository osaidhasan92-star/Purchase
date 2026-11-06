# Native Sales and Purchasing — phase 2

This phase converts the complete Sales and Purchasing transaction workspace to
React/strict TypeScript and canonical SQL headers/lines. It keeps the existing
`erp.html?view=…` addresses and the shared module menus, including dashboard/report
and comparison views. Converted routes load a compact bootstrap and bounded APIs;
they do not load or submit `/api/state` or `/api/hr/state` aggregates.

## Converted registers

| Register | Resource under `/api/trade/` | SQL header table |
| --- | --- | --- |
| Purchase requests | `requests` | `trade_purchase_request` |
| RFQs | `rfqs` | `trade_rfq` |
| Vendor quotations | `quotations` | `trade_vendor_quotation` |
| Comparison/award decisions | `comparisons` | `trade_comparison` |
| Purchase orders | `orders` | `trade_purchase_order` |
| Goods receipts | `receipts` | `trade_goods_receipt` |
| Vendor bills | `invoices` | `trade_vendor_bill` |
| Supplier payments | `payments` | `trade_vendor_payment` |
| Sales quotations | `salesQuotations` | `trade_sales_quotation` |
| Sales orders | `salesOrders` | `trade_sales_order` |
| Deliveries | `deliveries` | `trade_delivery` |
| Customer invoices | `customerInvoices` | `trade_customer_invoice` |
| Customer payments | `customerPayments` | `trade_customer_payment` |

Every header has a corresponding `_line` table for its historical/current line
arrays. Lines reference their header, product and, where applicable, original
source line. Header foreign keys link customers/vendors, leads and workflow
parents. RFQ invitations use `trade_rfq_vendor`, with vendor links and a retained
invitation snapshot. Source line ordinals remain stable even when an order repeats
the same product. `trade_command` stores actor/request-key idempotency receipts.

Core identifiers, status, dates, actors, partner information and monetary fields are
typed/indexed columns. Decimal calculations round PKR amounts to cents and quantities
to four decimal places; schema precision also preserves older stored values. Extension
JSON holds custom/historical attributes and field/type metadata, not entire registers.

## Server-owned operations

The browser sends selected references, dates, quantities and prices. The server
checks permissions, current record/source versions, valid references, line bounds
and workflow status. It creates document numbers, calculates taxes/discounts,
updates parents and records audit events. Users cannot submit forged totals,
creator identities or arbitrary posted statuses through these resource APIs.

- Request → submit/approve → RFQ → mark sent → invited supplier quotation →
  comparison/award → PO → submit/approve → mark sent → partial receipts →
  partial bills/match/approval → partial or full supplier payments.
- CRM lead → quotation draft/edit → approval → mark sent → record customer
  acceptance → confirmed Sales Order → partial deliveries/validation → partial
  invoices → partial or full customer payments.
- Requesters without edit permission submit demand directly as Pending Approval;
  managers still approve it. Other users may save a request draft before submission.
- Native POs may be direct or derived from an awarded quote. Customer orders require
  an accepted quote. Quoted order lines remain fixed. Shipping/services can be
  represented as service product lines; old shipping/discount headers are preserved.
- Pending deliveries reserve order quantities. Only validation moves stock; creation
  does not mean delivery or create an invoice automatically. Sales invoicing follows
  ordered quantities independently, so billing before delivery is also possible.
- Receipts enforce received = accepted + rejected. Only accepted goods increase
  stock; rejected quantities remain outstanding for replacement.
- Vendor bill approval checks accepted/unbilled quantities and value. Bills exceeding
  receipts remain match exceptions and cannot post until resolved. Payments cannot
  exceed actual remaining balances, and references cannot be reused accidentally.
- Orders complete only after full fulfilment, billing and payment. Paying the first
  partial bill never completes a partially received/delivered order.

Stock movements, immutable source journals, AR/AP entries, reconciliation, document
changes and command receipts commit in one transaction. Existing period locks and
negative-stock checks apply. Retrying the same command key does not double-post.
Stale edits/source choices return 409; missing required versions return 428. Each
financial command still needs the appropriate create/approve permissions.

Invoice net/tax cents are allocated cumulatively from original order lines across
split invoices. Native discounted receipts likewise allocate original line cents
across partial quantities, keeping inventory accrual and billed GRNI consistent.
Mixed stock/service vendor bills use their actual billed line allocation.

“Mark Sent” records workflow status; this phase does not configure or send SMTP mail.

## Permissions and bounded reads

Module/action permissions remain mandatory. SQL applies Sales creator/assigned team
and source-parent visibility before count/pagination; Finance retains company-wide
Sales access only for modules it may view. Purchase requests keep requester/team and
authorized Procurement/Finance access. Other Purchasing registers remain shared with
authorized departments. CRM notes are not copied into Sales documents.

Lists search/filter/count/page in SQL (25 rows by default, maximum 100). Lookup fields
search bounded lists and detail requests load one document/source graph. The dashboard
shows authorized SQL register counts/values across all statuses; it is not a substitute
for the posted Accounting reports. Customer details now query at most 25 scoped SQL
Sales Orders rather than scanning the full business aggregate.

Production `/api/state` PATCH requests touching converted transaction collections
return 410. This prevents bypassing the new action rules through the old aggregate
transport. Internal read adapters preserve exports, demo setup and remaining modules.
The old transport is explicitly enabled only in historical regression test fixtures.
A module's operators also need view access to the source registers used in its lookup
forms; permissions are not automatically expanded when configuring a custom role.

## Printing and attachments

Each authorized document offers **Print / PDF**, opening an authenticated escaped
HTML print layout. Use the browser's **Save as PDF** destination to download the PDF.
This includes draft quotations, purchase requests/RFQs/POs, receipt inspections,
invoices, supplier payments and customer receipts. Delivery challans include complete
source order/quotation lines and related invoice summaries when the reader also has
invoice view/export permissions. User-supplied text is escaped in both React and print
views. PDF attachments for requests, vendor quotes and POs retain protected downloads.

## Upgrade existing installations — Windows CMD

1. Stop Flask/all web workers. Back up the database and keep `.env` and attachments.
   For local SQLite, copy `instance\purchase.sqlite` while the server is stopped.
2. Extract the latest branch files, including all backend modules, frontend assets,
   `workspace.js`, `workspace-loader.js` and `trade-workspace.js`. Keep the database.
3. From your repository root, activate the existing virtual environment and run:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
set COOKIE_SECURE=false
python -m flask --app backend.app run --port 8000
```

Open `http://127.0.0.1:8000` and use your existing login. Do not reseed or create a
second administrator. Compiled assets are included, so Node is not required to test
this version on your desktop. Fresh installations initialize the new tables directly.

For Docker/PostgreSQL, take a database backup, rebuild the image, stop web workers,
and run `init-db` followed by `migrate-storage` in the new image before restarting web.

The migration upgrades both original JSON installations and the previous SQL-master
release. It checks exact round trips of all migrated arrays, retains IDs/order/custom
fields, removes the physical arrays and commits atomically. Repeating it is a no-op.
`init-db` alone does not silently migrate existing transaction data. The
migration never replays stock or accounting postings. The tests include an installation
with already posted receipts/bills/payments and verify unchanged ledger row counts.

Historical dangling references are retained explicitly as unresolved metadata, with
nullable SQL links; they are not replaced with invented parties/products. Such records
need administrative data correction before new commands can inherit those references.
Older bills without line allocations are retained, and their order forms show a review
notice; the server still enforces remaining received monetary value. Monetary values
that cannot round-trip safely stop migration rather than silently changing old data.

## Verification and remaining work

Backend tests cover complete trade days, partial fulfilment/billing/collection,
permissions, source and edit conflicts, command retries, overpayments/over-receipts,
match exceptions, scoped SQL pagination, rounding, normalized foreign keys and verified
migration without reposting. DOM checks keep all shared navigation/role tests and
remaining HR/production/expense workflows. Chromium tests exercise the native trade
forms end to end, draft editing/printing, comparison/award, CRM handoff and real ledger/
stock results. They also assert converted routes avoid aggregate requests.

HR/payroll records and administration still need their later migration. Accounting,
inventory, manufacturing and expense backend services are relational already, but
those screen contents still use the legacy HTML boundary. Legacy CRM company/quote
registers and configuration/attribution metadata remain outside this phase.

Read endpoints are bounded, but transaction commands currently reuse existing cross-
register validation/posting adapters, which materialize server-side compatibility
state and serialize through the company control lock. Further query-local validation,
load testing and concurrency tuning are required before claiming large-scale readiness.
Multi-company, multiwarehouse, multicurrency, statutory Pakistan localization and
full Odoo parity are not introduced by this phase.
