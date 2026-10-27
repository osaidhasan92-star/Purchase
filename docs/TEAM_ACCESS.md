# Creator, team manager and Admin access

Every business record is visible to its creator, that creator's current direct manager,
and Admin. Teammates do not see each other's records. This is one direct-manager level,
not recursive access for the manager's manager. A manager also sees their own records.
Users without a manager have creator/Admin access only.

Role permissions remain required: assigning a manager does not grant new module or
approval permissions. Admin can configure those under Users & Roles. CRM Manager,
Finance, HR Manager and Procurement Manager no longer have company-wide record
visibility merely because of their role. Admin retains company-wide access.

## Setup

1. Sign in as Admin and open Administration → Users & Roles.
2. Create the manager account and give its role the appropriate module permissions.
3. Edit each team member, select **Team manager**, and save.
4. Repeat for Procurement, Sales/CRM, HR, Finance and Manufacturing users as needed.

The Team manager field is available for every role. Self-management and management
cycles are rejected. A manager change immediately changes access to the employee's
historical records; ownership does not change. A user-account change revokes that
user's existing login sessions, so they should sign in again.

## Coverage

The same rule covers customer/vendor/product masters, CRM leads/reminders/quotes,
purchase requests/RFQs/quotations/comparisons/orders/receipts/bills/payments,
sales quotations/orders/deliveries/invoices/payments, every HR register,
BoMs, manufacturing orders, expense claims, custom accounts, journals,
bank statements, stock movements, attachments and activity entries.

Server-side filtering applies to lists, direct-ID actions, parent references,
report lines and dashboard aggregates. A guessed record ID or a forged creator
cannot grant access. Hidden records are preserved when somebody else saves a
visible subset of a register. Creator identity is immutable through normal saves.
Automatic journals and stock movements retain the source creator when a manager
approves or completes the source document.

Standard system reference data (the built-in chart of accounts, Pakistan/PKR,
company identity and warehouse configuration) remains available where a module
needs it. These are system settings; user-created business records are private.
A customer or product created by Admin is Admin-owned, not a public master record.
Demo opening records are likewise Admin-owned.

Financial reports and dashboard totals are scoped views; only Admin gets the
company-wide totals. Inventory lists show the visible stock movements' quantities
and values. The physical single-warehouse stock ledger remains shared internally
for actual stock validation and perpetual valuation; ownership filtering does not
create separate warehouses or duplicate stock.

## Existing databases

Back up the database, update the application files and restart the server. Ownership
metadata uses the existing Document table; no schema migration or reseeding is needed.

Existing records with a reliable `createdBy` (or a legacy `ownerId`) retain that
attribution. Existing journals use their recorded creator and existing expenses use
their owner. Unattributed legacy records are Admin-only, rather than being exposed
company-wide or attributed to whichever user first opens them.

After reviewing an unattributed legacy record's true creator, a server administrator
can attribute it using the Flask CLI, for example from the project root:

```text
flask --app backend.app assign-legacy-owner --namespace app --collection rfqs --record-id 123 --creator-email staff@example.com
flask --app backend.app assign-legacy-owner --namespace hr --collection employees --record-id EMP-OLD --creator-email hr@example.com
flask --app backend.app assign-legacy-owner --namespace bom --record-id 1 --creator-email production@example.com
```

Supported relational namespaces are `bom`, `manufacturing`, `bank` and `account`.
The command refuses to overwrite a known creator and audits the reviewed attribution.
For aggregate source documents, existing generated journals and linked stock movements
follow that reviewed creator. Review related customers/vendors/products and other
upstream documents separately; attribution does not silently share a whole chain.

Reassigning a lead's salesperson is a workflow assignment, not a record-visibility
grant. Creator-based access still applies. If a process needs colleague-to-colleague
handoff, use the manager/Admin workflow; arbitrary sharing is not part of this policy.
