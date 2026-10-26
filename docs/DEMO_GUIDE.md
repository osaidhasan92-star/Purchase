# Client demonstration — Pakistan general products

## Start

1. Follow the README to initialize the database and create an administrator.
2. Sign in. The landing page is **ERP Overview**, with Pakistan, PKR and WH / Stock.
3. On an empty installation, click **Load demo opening data**. This adds:
   - Main Bank PKR 250,000 and Cash on Hand PKR 25,000.
   - 100 General Panels at PKR 500 cost and 200 Fastener Packs at PKR 50.
   - A General Assembly Kit and Installation Service catalog entry.
   - A BoM: 2 panels + 4 fastener packs + PKR 100 conversion cost per kit.
4. Company identity/contact details are available from **Company profile** on the
   overview. Country/currency and the warehouse are fixed. There is no separate
   Company Settings page.

Demo opening data cannot overwrite an existing ledger or existing product catalog.
Use a separate empty database for a clean presentation, never erase client data.

## Consistent module navigation

The sidebar lists modules. Click CRM, Sales, Purchasing, HR, Accounting, Inventory,
Manufacturing or Expenses to open its dashboard. Each module uses the same header,
horizontal submenu and workflow strip; the dark tab indicates the current screen.
Submenu links are filtered by the signed-in user's permissions. On small screens,
the module menu opens from the header and submenu tabs scroll horizontally.

- CRM: Dashboard, Leads, Customers, Reminders.
- Sales: Dashboard, Customers, Quotations, Orders, Deliveries, Invoices, Payments.
- Purchasing: Dashboard, Requests, RFQs, Quotations, Comparison, Orders, Receipts,
  Bills, Payments, Vendors, Products, Reports.
- HR: Dashboard, Employees, Manpower, Recruitment, Attendance, Leave, Payroll,
  Separation, Reports.
- Accounting: Dashboard, Chart of Accounts, Journals, Financial Reports,
  Receivables / Payables, Bank Reconciliation.
- Inventory: Dashboard, Products, Stock Movements.
- Manufacturing: Dashboard, Manufacturing Orders, Bills of Materials.
- Expenses: Dashboard, Expense Claims.

Customers opened from CRM retain the CRM submenu, and Products opened from
Purchasing retain the Purchasing submenu. Administration also shares the same
layout for users/roles, activities and import/export.

## Manufacturing → inventory → finance

1. Open **Manufacturing → New Manufacturing Order**.
2. Select the standard kit BoM and quantity 2. Save, Confirm, Start, then Mark Done.
3. Open **Inventory**. Panels should be 96, fastener packs 192 and kits 2.
4. Kit value is PKR 2,600: components PKR 2,400 plus conversion PKR 200.
5. In **Accounting → Journals**, inspect component consumption into WIP, conversion
   accrual and finished-goods valuation. WIP clears to zero. Costs are posted once
   even if a completed order's action is repeated.
6. Try to produce more than available components. Completion is rejected, and the
   transaction leaves inventory and journals unchanged.

## CRM → sales → delivery → customer receipt

1. Create a lead for the demo customer, with stage **Quotation Required**.
2. Use **Open in Sales**, select the kit and enter quantity/rate. Save Draft or
   Submit for Approval. Draft editing retains selected products.
3. Approve the quotation as the assigned Sales Manager or Admin. Send to Customer,
   record Customer Accepted, then create the Sales Order.
4. CRM should show the quotation stage changes, then Closed Won on acceptance.
5. In **Deliveries**, create a delivery. It remains Pending until Mark Delivered.
   Only Mark Delivered reduces stock and posts cost of goods sold. Services do
   not move inventory. A delivery with insufficient stock is rejected atomically.
6. In **Customer Invoices**, create an invoice from the order. Invoice policy is
   ordered quantity, so advance invoicing is possible before delivery.
7. In **Customer Payments**, receive part of the invoice, then the remainder.
   Observe invoice balances, bank/cash entries and automatic receivable matching.
8. Open **Accounting → Receivables / Payables** to review remaining open items.

## Request → purchase → partial receipt → supplier payment

1. Create and approve a Purchase Request.
2. Create an RFQ and select vendors. Mark it Sent, then record vendor quotations.
3. Compare quotations and select a supplier. Create and approve the Purchase Order,
   then mark it Sent to Vendor.
4. Receive part of the order through Goods Receipts. Stock and GRNI post at receipt.
5. Record a supplier invoice for the accepted amount, approve it, then pay it.
   The bill clears the accrued receipt value to AP; payment clears AP to cash/bank.
6. Paying the first partial bill must not complete the entire PO. Receive the rest,
   record the remaining bill and pay it. Only fully received and fully paid orders
   are completed by the payment flow.
7. An invoice cannot allocate more than the ordered and accepted unbilled value.
8. In Inventory, a linked receipt/delivery return reverses stock valuation. A
   commercial credit/refund is a separate reviewed accounting step in this demo.

## Expenses

1. Create an expense, optionally attach a PDF receipt, then Submit.
2. Finance/Admin approves it: expense and employee payable post automatically.
3. Reimburse using Cash or Main Bank: the employee payable clears automatically.
4. Staff can view their own claims. Finance/Admin can review and approve claims.

## HR and payroll

1. Add payroll employees; system login accounts remain optional and administrator
   controlled. Record attendance and leave. Duplicate daily attendance, overlapping
   non-rejected leave and duplicate monthly payroll entries are rejected.
2. Prepare a monthly payroll with basic salary, allowances and deductions.
3. Approve: debit salary expense for gross pay; credit salaries payable for net
   pay and deductions payable for deductions.
4. Mark Paid: debit salaries payable and credit Main Bank. View the journal from
   the payroll action or Accounting → Journals. Print the paid payslip.
5. Completing separation disables the linked non-admin login and revokes its
   sessions. Administrator offboarding requires explicit review in User Management.

Attendance/leave do not calculate statutory payroll deductions automatically.
Payroll entry amounts are entered for the demonstration; posting is automatic.

## Accounting and finance

- **Chart of Accounts**: review seeded accounts or add a new account.
- **Journals**: save a balanced manual draft, Post, then Reverse when needed.
- **Internal Transfer**: move cash ↔ bank without recording income or expense.
- **Receivables / Payables**: inspect open items; match compatible debit/credit lines.
- **Bank Reconciliation**: record a signed statement line, then match an unmatched
  posted bank/cash journal item with the same amount. Matching creates no new payment.
- **Financial Reports**: filter dates; inspect P&L, balance sheet, trial balance,
  general ledger and cash movements; export ledger CSV. Balance check must be zero.
- **Lock Accounting Period**: reject new entries/stock postings dated on or before
  the lock date. Only an administrator can change or remove the lock.

This is a connected demonstration, not an assertion of FBR or statutory payroll
compliance or full feature parity with Odoo. Use the README's boundaries when
describing the system to clients.
