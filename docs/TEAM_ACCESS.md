# Department access and record privacy

This single-company, single-warehouse ERP uses department permissions for business
handoffs. Creator identity is retained for accountability; it is not a universal
record-sharing restriction. Admin can access all company records.

| Area | Record visibility, after module permission checks |
| --- | --- |
| CRM leads / legacy CRM quotes | Creator, assigned salesperson, their direct managers, Admin |
| CRM reminders | Creator/manager or users authorized for the linked private lead |
| Customer/vendor/product/company masters | Shared with authorized modules/departments |
| Purchase requests | Requester's team; authorized Procurement and Finance users |
| RFQs, vendor quotes, comparison, POs, receipts, bills, payments | Shared with users authorized for each purchasing/Finance module |
| Sales quotes, orders, deliveries, invoices and payments | Creator/assigned Sales team; source workflow participants; Finance where its module permissions permit |
| Inventory, stock moves, BoMs, manufacturing orders | Shared with authorized inventory/production users in this one-company/warehouse deployment |
| Accounting, custom accounts, journals, reports, bank statements | Company-wide for users authorized for Accounting |
| HR records | Authorized HR staff; employees see only their own linked records when self-service view permission is granted |
| Payroll | HR administration or the employee's own linked payroll records; not ordinary sales/team-manager access |
| Expense claims and receipts | Submitter, their direct manager, authorized Finance users, Admin |
| Activity log | Actor/direct manager, Admin; account administration and full audit export remain Admin-only |

Module/action permissions remain mandatory. Shared visibility does not grant editing,
approval, account management or access to an otherwise disabled module. A read-only
Viewer cannot mutate shared records. A person with Accounting permission receives
company-wide financial visibility, including payroll journal amounts; Finance access
must therefore be limited to authorized personnel. HR payroll registers are separately
protected by HR permissions.

## Setup in Users & Roles

1. As Admin, create users with the appropriate Sales, CRM, Procurement, Finance, HR
   or Manufacturing role.
2. Set **Team manager** for Sales users and other staff whose claims/requests need
   managerial oversight. Managers need appropriate module/action permissions.
3. Review role permissions for creation, approval and payments separately. A manager
   who may approve expenses needs Expenses approval permission. Reimbursement also
   requires Accounting access, so a non-Finance manager cannot pay a claim.
4. For employee self-service, link the employee record to their login account. Grant
   only the needed HR view/export permissions; do not grant HR Employees edit permission
   unless that role is authorized to administer company-wide HR records. Self-service
   employees cannot create/edit their salary or approve their own payroll through view access.

Direct-manager and same-manager Sales-team membership is evaluated from current user
accounts. Self-management and management cycles are rejected. A manager change updates
team access to historic records. Existing custom role permissions are preserved.

## CRM to Sales handoff

CRM creates a shared customer, creates a private lead, and selects **Assign Salesperson**.
CRM Manager may select an active Salesperson/Representative; Admin may assign any
appropriate user; a Sales Manager can assign direct reports. Assignment does not change
who originally created the lead. The assignee and their manager can open the opportunity;
unrelated salespeople cannot read its private notes.

Quotations and subsequent Sales transactions support the assigned Sales team. An
existing authorized quotation can be progressed without exposing the private lead to
every teammate. The server updates the linked lead's quotation stage/status, preserving
its notes and creator. Finance can access orders/invoices/payments where authorized,
without needing permission to read CRM leads.

## Inventory and accounting

Authorized inventory users see the actual warehouse stock quantities, movements and
valuation. Production can use shared products and BoMs created by another authorized
user. Finance sees complete company journals, balances and reports regardless of the
source creator or department. Source creator metadata is retained on automatic postings.
This avoids incomplete company reports and duplicate master records.

This is one company and warehouse: there is no separate warehouse/site isolation or
arbitrary per-document sharing interface. Multi-company/multiwarehouse departments
would need additional organization scopes.

## Updating an existing installation

Back up the database, update application files and restart the server. No schema
migration, ownership rewrite, `init-db` or demo reseeding is needed. Shared operational
records become visible according to current department permissions. Private legacy CRM
records with no reliable creator or assignee remain Admin-only until reviewed; HR and
accounting use their department policies, not missing creator metadata.

The reviewed legacy-attribution CLI remains available for audit cleanup, for example:

```text
flask --app backend.app assign-legacy-owner --namespace app --collection leads --record-id 123 --creator-email crm@example.com
```

It never overwrites a known creator. Attribution is audit metadata; it does not make
operational records private or bypass department/assignment permissions.
