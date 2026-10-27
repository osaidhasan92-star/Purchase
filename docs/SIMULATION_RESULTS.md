# Simulation results — current migration coverage

The original 26 October baseline is retained below. The Sales/Purchasing phase adds
native React form execution in Chromium and canonical SQL header/line storage.
[Phase 2](TRADE_MIGRATION.md) describes current scope and upgrade instructions.

Current checks include 63 backend scenarios, 48 shared screen/view renders and real
browser flows: request → RFQ → comparison/award → PO → two receipts/bills → partial
and full payments; CRM lead → draft edit/print → approval/acceptance → order → two
deliveries/invoices → partial and full collections. Backend cases independently
check quantities, PKR totals, split tax rounding, discounted GRNI clearing, source
foreign keys, migration of posted data without reposting, private Sales pagination,
version conflicts and command idempotency. Native routes are checked for compact
network access without business/HR aggregate loading or saving.

## Earlier baseline — 26 October 2026

Tested branch: `codex/database-backend`. Tests use isolated, temporary SQLite databases;
no client or production data is used or changed.

## Executed coverage

- 29 backend tests: authentication, CSRF, permissions, session revocation, PDF access,
  version conflicts, persistence across app instances, posting validation and ERP scenarios.
- 48 screen/view renders using jsdom against the real Flask HTTP backend, with actual
  form submission and action handlers. Checks cover the single workspace URL, active tabs,
  shared customer/product context, and restricted roles.
- CRM lead handoff to sales; quotation approval, acceptance, order, delivery, invoice,
  partial customer collection; purchasing with two partial receipts, bills and payments.
- BOM manufacturing: draft, confirm, start, complete; component consumption, finished
  goods cost, conversion accrual and WIP clearance. Insufficient components roll back.
- Expense submission, approval and bank reimbursement; payroll approval and bank
  payment automatically post journals.
- Manpower request approval, candidate record creation, employee creation, attendance,
  leave approval and separation. Duplicate attendance and overlapping leave are blocked.
  A separate backend scenario verifies separation revokes a linked login.
- Manual journal balance rejection, draft/post/reverse, cash/bank transfer, statement
  matching and period-lock enforcement.
- Customer/vendor stock returns, duplicate return idempotency and excessive-return
  rejection; negative stock, overbilling, overpayments and posted document edits rejected.
- Admin-only company profile in the dropdown, including opening it outside the overview.

## Combined business-day scenario

A single fresh company is seeded with cash PKR 25,000, bank PKR 250,000,
100 panels at PKR 500 and 200 fastener packs at PKR 50.

The simulation receives two additional panels for PKR 1,000 and pays the vendor;
delivers one panel and invoices PKR 1,500; collects PKR 600 and then PKR 900;
manufactures two kits using four panels, eight fastener packs and PKR 200 conversion;
pays PKR 1,250 travel expense; approves PKR 55,000 gross payroll with PKR 2,000
deductions and pays PKR 53,000 net; then transfers PKR 5,000 bank to cash and
matches the bank statement line.

| Final check | Expected and actual |
| --- | ---: |
| Panels on hand | 97 |
| Fastener packs on hand | 192 |
| Finished kits on hand | 2 |
| Total inventory value | PKR 60,700 |
| Cash | PKR 31,500 |
| Bank | PKR 189,750 |
| Cash + bank | PKR 221,250 |
| Customer receivables | PKR 0 |
| Vendor accounts payable | PKR 0 |
| Work in progress | PKR 0 |
| Profit / (loss) | PKR (55,250) |
| Balance sheet difference | PKR 0 |

Every journal's debits equal credits. The stock valuation matches inventory account 1200.
A new authenticated session reads the same final reports. Deductions and conversion
accrual remain liabilities; zero vendor payable does not mean all liabilities are zero.

## Reproduce

From the repository root, install backend requirements and pytest, then run:

```text
python -m pytest backend -q
npm ci
npm run test:dom
```

`test_complete_demo_business_day` and `test_customer_and_vendor_stock_returns` in
`backend/test_demo_simulation.py` retain the new scenarios for subsequent CI runs.

## Scope and remaining limits

The earlier baseline below used API/DOM execution. Current phase checks additionally
exercise Chromium native forms and print layouts, including responsive behavior.
They do not establish production load or deployment acceptance. PostgreSQL is covered
by the repository CI job; local backend runs use SQLite.

Recruitment is a candidate register: selecting Hired does not automatically create an
employee. Create the employee separately. Stock returns update physical stock and
related cost postings; commercial refunds/credit notes are separate. Separation records
store final-settlement amounts but do not provide a complete final-settlement accounting
workflow. Attendance and leave do not automatically calculate payroll deductions.
Pakistan statutory payroll/tax filing, advanced manufacturing planning and full Odoo
feature parity remain outside this demo. Passing these tests establishes the executed
scenarios, not every possible user action or production readiness.
