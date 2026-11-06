# Reservations, backorders and internal locations

## Upgrade

This release adds location balances, reservations, backorders, internal transfers and warehouse request receipts. Stop the application and, with its Python environment activated, run from the repository root:

```shell
python -m flask --app backend.app migrate-storage
```

Restart the backend and hard-refresh the browser. The migration initializes existing on-hand balances in **Stock**, preserving company-wide quantities, valuation and posted journals. Historical location splits are not inferred. Existing sales orders are considered oldest first when initializing reservations. Re-running the migration preserves existing locations/transfers and does not repost stock or accounting entries.

## Sales reservations

Creating a confirmed sales order reserves the available **Stock-location** quantity. Other orders cannot reserve that quantity again. An order with insufficient stock remains open and shows Waiting Stock or Partially Available. Service products need no physical stock reservation.

Use **Check Availability** on a sales order, or Inventory → Warehouse Operations → Reservations/Backorders, after new stock arrives or staged/returned goods are transferred to Stock. Waiting orders are not automatically reassigned whenever a receipt arrives; the explicit availability check controls assignment. **Release Reservation** on the order (or **Release Order Stock** in the warehouse register) pauses its reservation and frees stock. Check Availability resumes assignment.

New deliveries default to quantities available to dispatch. The backend also rejects dispatch beyond the order's own reservation, including quantities already assigned to pending deliveries. Validation consumes the reservation together with the stock movement. Other sales orders, scrap, negative adjustments and manufacturing cannot consume stock held for that order.

Cancel pending deliveries and invoice drafts before cancelling an unfulfilled sales order. Cancelling releases its reservations. Orders with delivered goods or posted financial documents cannot use that cancellation path. Partially fulfilled orders can release stock while retaining their open remainder; closing/cancelling a fulfilled order's financial obligations is not part of this workflow.

## Backorders

Partial actual receipts and validated deliveries create numbered **BO-P / BO-S** records for the remaining original-order quantities. The records retain the originating document and line, update across further partial fulfillment and close at zero. Follow-up receipts/deliveries carry the backorder reference. Returns can reopen remaining fulfillment quantities.

Open Inventory → Warehouse Operations → Backorders. Sales backorders show Waiting Stock, Partially Available or Ready. **Fulfill Backorder** opens the existing receipt/delivery form for the original order, with its current quantity limits. This can fulfill multiple remaining lines of that order together. Enter the actual partial quantity before saving/validating; to change a pending delivery, cancel it and create the correctly sized delivery. This release does not split a pending delivery into a new picking automatically.

Sales-order identities and quantities in reservations/backorders follow the existing sales-order view and team scope. Purchase backorders follow the existing purchase-order permissions. Warehouse-level physical location balances remain shared with authorized Inventory viewers, consistent with existing stock balances.

## Internal locations and transfers

Inventory → Warehouse Operations → Locations & Availability displays quantities in **Stock**, **Production** and **Returns**, plus sales reservations and unreserved Stock availability.

- Receipts, positive adjustments and manufactured outputs enter Stock.
- Customer returns enter Returns and cannot be dispatched directly.
- Sales deliveries leave Stock against their order reservation.
- Manufacturing consumes Production staging first, then unreserved Stock. It cannot use quarantined Returns or another order's reserved Stock.
- Other negative movements consume unreserved Stock.

**New Internal Transfer** moves an approved quantity between the three locations. Transfers out of Stock cannot take reserved quantities. Transfer records are immutable, reasoned and date/period-checked; inventory creation and approval permissions are required. They appear in the Internal Transfers register, independently of the financial stock-movement register. Moving a quantity internally does not change the product's company-wide on-hand quantity, average valuation or accounting journals. Per-location valuation/cost layers are not introduced; valuation remains the existing one-company product-average model.

## Integrity and verification

Commands participate in the existing transaction and request-key/version controls. Reservations share product locks with native stock and manufacturing writers; internal warehouse commands use the compatibility serialization gate. Locations cannot go negative. Source order limits, pending delivery quantities and reservations are all enforced by the server. Products with stock history or open stock reservation obligations cannot change product type.

`backend/test_warehouse_api.py` covers competing and simultaneous confirmations, reservation release/resume, shared-source limits, backorder closure, return quarantine, internal transfer value/journal conservation, stale/duplicate requests, read/write permissions, manufacturing staging, product type protection and migration preservation. `tests/warehouse-browser.cjs` covers real transfer and backorder fulfillment actions and desktop/mobile forms. PostgreSQL concurrency/load verification is still required in the deployment environment; local SQLite tests are not a capacity claim.
