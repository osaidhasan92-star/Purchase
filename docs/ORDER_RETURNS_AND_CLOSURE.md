# Order returns, credits, replacements and remainder closure

## Sales

1. Open a Sales Order. **Fulfillment, returns and credits** shows original ordered,
   gross delivered, returned, net fulfilled, invoiced, credited, open and closed quantities.
2. Related fulfillment documents link to the delivery and its **Return goods / stock
   history**. Open the original Sales Delivery stock movement and choose Return Stock.
   Only validated, not-yet-returned quantities can be returned.
3. Customer returns enter Returns quarantine. Open **Inspect returned goods**, then
   **Inspect / Restock** for the product. Verify its physical condition, transfer only
   usable quantities to Stock, and record the inspection decision as the transfer reason.
   This is an approved internal transfer, not a separate quality inspection register.
   Unusable quantities remain quarantined for separate disposition; they are not
   automatically restocked, disposed of or financially credited.
4. From the related posted invoice choose **Create credit note**. Allocate validated
   return quantities, review and post in Accounting. Posting automatically applies
   credit to the original unpaid balance; remaining credit can be applied to another
   eligible invoice or refunded. The order links to the credit's existing settlement
   screen. A physical return alone does not refund money.
5. For replacement, leave the order open and Check Availability after replenishment
   or inspection/restock. **Create Replacement Delivery** uses the existing order's
   remaining quantity and reservation controls. Its quantity includes both undelivered
   original demand and returned quantities requiring replacement; verify actual dispatch.
6. If the customer declines the remainder, choose **Close Remaining Quantity** in
   order details, enter the reason and Approve Closure.

## Purchasing

Related receipts link to original receipt stock movements for returns of previously
accepted goods. From the related vendor bill create and post a vendor credit; apply
it to eligible bills or record the supplier's refund in Accounting. Replacements are
received against the same open PO with its remaining accepted-quantity limits.

Receipt quantities rejected during inspection never enter inventory, so they do not
need an inventory issue to remove them. The receipt inspection records the rejection
and reason. If the supplier was not billed for them, there is no corresponding
financial credit to create. Previously accepted goods follow the stock-return and
vendor-credit flow. An entirely rejected receipt can close the unfulfilled PO remainder.

## Approved closure

Closure requires the order module's **approve** permission, source-record/team access,
current version, a request key and a nonempty reason (maximum 500 characters).
It applies to approved orders with fulfillment/inspection activity and a remaining
quantity. Validate or cancel pending deliveries first. Cancel excess invoice drafts,
or resolve excess invoiced quantities through Finance credits, before closing.
Historical invoices without usable line quantities require Finance review and block
closure rather than guessing quantities.

Closure stores the per-line unfulfilled quantity, fulfilled snapshot, reason, approver
and time; releases Sales reservations and cancels open operational backorders. The
original ordered quantities and agreed values remain unchanged. Closed orders reject
new receipts/deliveries and cannot be reopened or edited. A new commercial requirement
needs a new approved order. Subsequent returns and credits remain possible against
original documents but do not reopen fulfillment or reserve replacement stock.

Closure does not create/reverse journals, void posted invoices, forgive debts, cancel
payments, create credit notes or refund money. Fulfilled unbilled quantities can still
be invoiced/billed, capped by net fulfillment and the quantity retained at closure,
including products configured for ordered-quantity invoicing. Existing payments and
credit settlements continue normally, with financial statuses refreshed while the
order remains Closed. Fully credited orders show Fully Credited / No Balance Due;
any unapplied/refundable credit remains a separate obligation in the credit register.
The closure cannot silently authorize another invoice for a
returned or cancelled quantity.

The reason and approver appear in details and print layouts. Order print layouts also
show the fulfillment/return/credit quantities. Restricted invoice/credit figures show
Unavailable; related document links require each register's permissions and existing
record scope. Lists of related documents are bounded to 25 per register. Credit
quantities are posted credit-note quantities, independently of credit settlement.

## Upgrade and verification

This phase uses existing relational document extension fields and stock/credit APIs;
there are no additional tables or schema migrations. Install the updated sources and
compiled frontend bundle, restart the backend and hard-refresh. If upgrading from
before the warehouse/manufacturing phases, run their documented `migrate-storage`
upgrade first. Keep the existing database, environment, attachments and login.

`backend/test_order_resolution.py` covers return/credit/refund and closure for Sales
and Purchasing, pending deliveries and excess drafts, version/replay checks, approval
permissions, restricted quantities, rejected receipts, post-closure billing/payment
and later returns without reopened demand. The browser audit covers related credit
settlement, inspection/restock, summaries, approved closure, journal conservation and
desktop/mobile Cancel. Production load and PostgreSQL environment validation remain
separate requirements; this is not full Odoo parity or enterprise capacity certification.
