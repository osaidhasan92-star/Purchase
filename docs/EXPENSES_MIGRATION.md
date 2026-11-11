# Native Expenses — phase 7

Expenses now uses React/strict TypeScript contents in the shared `erp.html?view=expenses`
and `erp.html?view=expense-claims` shell. Claims remain in the existing relational
`expense` table. Native pages use compact bootstrap and scoped, paginated SQL reads;
they do not load the legacy ERP renderer or business/HR aggregate documents.

## Client demonstration

1. Open Expenses → New Expense. Enter description, expense date, expense account,
   amount and optional manually entered tax. Optionally upload a PDF receipt up to
   10 MB. The server records the signed-in user's identity and name as claimant.
2. Save Expense creates a Draft; it does not post a journal.
3. Open the claim and Submit. An authorized approver can Approve or Reject.
4. Approval debits the selected expense account and input tax (1300), and credits
   Employee Reimbursements Payable (2350). Period locks apply to the expense date.
5. An approver who also has Accounting access can Reimburse. Choose Bank (1010)
   or Cash (1000) and a payment date. The payment debits 2350 and credits the chosen
   payment account; automatic reconciliation clears the employee payable.
6. Inspect the claim's receipt, authenticated Print / Save as PDF, and authorized
   approval/reimbursement journal links. Filter claims by text, status and dates.

Rejected claims are terminal: create a new claim to resubmit. Editing, deletion,
reopening, advances, split reimbursements and cancellation/reversal workflows are
outside this phase. Claims are paid in full. Tax is a demo ledger entry, not Pakistan
statutory tax validation, recoverability assessment or FBR integration.

## Visibility and actions

Expense view permission is mandatory. Admin and authorized Finance can see all
claims; other users see their own and their direct reports' claims. This scope is
applied in SQL before pagination, totals and search. Unrelated claim IDs return 404.
The dashboard describes scoped totals rather than implying company totals.

Create requires Expenses create. Submit requires edit and ownership or approval
permission. Approve/reject require edit + approve. Reimburse additionally requires
Accounting view. Print requires export. The API supplies available actions, and
checks permissions again when commands execute. Direct managers do not automatically
receive approval grants. The PDF endpoint retains its existing uploader/direct-manager/
Finance scope and requires the corresponding module permission.

Native creation accepts no owner or employee override. Existing historical claims
retain their original employee/owner values. Legacy APIs remain compatible, sharing
the same posting transition service; the new browser uses native endpoints only.

## API and safeguards

| Resource under `/api/expenses` | Purpose |
| --- | --- |
| `GET /summary` | Scoped SQL status counts and amount totals |
| `GET /claims` | Scoped search/status/date filters, 25 per page, maximum 100 |
| `GET /claims/<id>` | One claim, current version and allowed actions |
| `GET /accounts` | Bounded expense-account choices |
| `GET /claims/<id>/print` | Authenticated escaped print layout |
| `POST /commands/<action>` | create, submit, approve, reject, pay |

Each command requires an actor-scoped idempotency key. Reusing a key with different
inputs returns 409. State changes require the current claim version: missing 428,
stale 409. Commands serialize with the shared ERP lock. Receipt validation, posting,
reconciliation, command receipt, audit and state change commit atomically. Failed
posting rolls back the claim and journals. Existing session cookies and CSRF apply.

`init-db` adds the `expense_command` receipt table without rewriting claims or
reposting history. No opening balances or demo records are automatically added.

## Windows upgrade

Stop the server, back up the existing `instance` directory/database, and keep the
current environment/database settings. Replace application files using the latest
`codex/database-backend` branch ZIP. From the actual project root in CMD:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app run --host 127.0.0.1 --port 5000
```

Open `http://127.0.0.1:5000/erp.html?view=expenses` and sign in with your existing
account. Do not reseed or recreate Admin. Built frontend files are included, so
Node is not needed for desktop testing. Hard-refresh the browser after upgrading.

## Verification

Five new backend simulations cover posted balances and reconciliation, permission
and SQL privacy boundaries, versions/replays, input validation, protected receipts,
pagination/search, escaped printing, period-lock rollback and aggregate-free native
reads/actions. DOM checks exercise all 48 shared routes. Chromium uses the real
claim form with PDF upload, submission, approval, cash reimbursement, status/search
filters, rejection, print links, balanced ledger and a 390px mobile dialog.

Administration remains the next native module conversion; legacy CRM company/quote
screens and configuration/creator metadata remain outside completed native slices.
