# Returns, credit notes and refunds

## Install / upgrade

This version adds `credit_note`, `credit_line`, `credit_settlement` and `credit_command` tables, plus a lookup index on stock-return references. With the application stopped, use the existing database and run from the repository root (with its Python environment activated):

```shell
python -m flask --app backend.app migrate-storage
```

The command creates missing tables and preserves existing records. Restart the backend and hard-refresh the browser. Keep legacy aggregate trade writes disabled in production. The database backup/restore process must include the new tables.

## Customer return

1. Open Inventory → Deliveries, locate the original delivery and choose **Returns / Stock**.
2. View its stock movement, choose **Return Stock**, enter the actual quantity, date and reason. This requires Inventory approval permission.
3. Open the posted customer invoice and choose **Create Credit Note**, or Accounting → Customers → Credit Notes & Refunds → New Credit Note.
4. Select the original invoice. Enter a reason, credit date, invoice-line quantities and the corresponding validated stock returns. Services do not need stock returns.
5. Save Draft Credit → Submit for Review → Post Credit Note. Posting requires Accounting approval permission.
6. The credit automatically clears the original invoice's unpaid balance, up to the credit amount. Any remaining credit can be refunded to the customer, or applied to another open invoice for that customer.

## Vendor return

Use Inventory → Receipts → Returns / Stock to validate the outgoing return. Create a vendor credit from the original posted bill, or Accounting → Vendors → Credit Notes & Refunds. Post the credit, then apply any remaining balance to another bill for the same vendor or register the vendor refund received into bank/cash.

The pre-existing vendor bill status `Approved` denotes a posted payable. Customer invoices use `Posted`.

## Controls and accounting

- Stock returns must reference the original receipt/delivery. Direction, product, order and order-line linkage must match the credited invoice line.
- Active drafts reserve invoice and return quantities; cancelling an unposted draft releases that reservation. Quantities cannot be credited beyond the invoice quantity or validated return quantity, including across split invoices.
- Amounts, taxes and return-cost allocations are calculated from original records using cumulative decimal rounding. Clients cannot supply credit prices or journal amounts.
- Drafts create no ledger entries. Posted credits and refunds are immutable; corrections/reversals of posted credit documents are not part of this workflow.
- Customer credits reverse revenue/output tax and credit receivables. Vendor credits debit payables and reverse input tax and receipt accrual/expense. Vendor return cost differences post to Stock Adjustments and Scrap, preventing receipt accrual from remaining stranded when average stock cost differs from the bill price.
- Physical return journals update inventory/COGS or receipt accrual; a credit note does not move stock a second time.
- Credits apply automatically to the original unpaid invoice/bill. Refunds and further applications cannot exceed available credit. Cross-partner applications and payments above the net invoice balance are rejected.
- Applied credits and cash payments are tracked separately. The original invoice amount is retained; outstanding balance includes recorded credit applications.
- Returns reduce net received/delivered quantities. Posted credits release the corresponding invoiced quantities, permitting replacements and reinvoicing within the original order limits.
- Dates cannot precede source documents. Posting/refunds/applications respect accounting period locks. Generic ledger matching cannot bypass credit settlement actions and leave trade balances unsynchronized.
- Writes are transactional with request-key retries and version checks. Credit commands use the existing compatibility serialization gate; PostgreSQL performance/concurrency expansion of these new commands remains separate work. Inventory returns acquire the affected trade graph locks in resource-concurrency mode.
- Historical invoices without usable source lines require accounting review; this API does not fabricate missing quantities or return links. Credit printing, debit notes and credit-note reversals are not included here.

## Verification

`backend/test_credit_api.py` covers customer and vendor partial returns, original/return quantity caps, unpaid-balance application, paid refunds, same-partner applications, wrong-partner rejection, immutable settlement limits, retry idempotency, review permissions, stale versions, draft cancellation, period locks, services, replacement quantities and vendor average-cost variance.

`tests/credits-browser.cjs` exercises the real customer return/draft/review/post/refund flow and desktop/mobile forms. It runs as part of `npm run test:browser`. Database-specific concurrency checks require the existing PostgreSQL test setup; SQLite results do not establish PostgreSQL load capacity.
