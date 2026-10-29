# Native Accounting and Finance — phase 4

Accounting dashboard, Chart of Accounts, Journals, Financial Reports,
Receivables/Payables and Bank Reconciliation now use React/strict TypeScript in the
existing `erp.html?view=…` workspace. The shared menus and Admin-only company profile
remain. Converted routes load compact bootstrap and bounded SQL resource APIs;
they do not load business/HR aggregates or the legacy finance renderer.

## Workflows

- Add an account using a unique 4–8 digit code and account type; optionally enable
  reconciliation. Existing/chart account identities remain unchanged.
- Create a balanced journal draft with 2–100 debit/credit lines. Add partner keys and
  due dates where needed. Edit only manual drafts, then explicitly Post. Automatic
  sales, purchasing, payroll, expense and stock postings remain visible in Journals.
- View an individual journal and print an escaped authenticated journal PDF layout
  through browser Print / Save as PDF. Source-filter links from existing modules
  continue to select the matching journal family. Eligible trade documents/payslips
  have a source-print link only with the required source view/export permissions
  and record scope. Accounting access alone does not grant private HR source access.
- Reverse an unreversed, posted manual journal or cash/bank transfer on an open
  posting date. Entries with reconciled items or bank matches require accounting
  review first; source-generated economic documents use their own correction flows.
  The original and reversing entries both stay Posted, with explicit reversal links.
- Dashboard → Bank / Cash Transfer posts between Cash on Hand (1000) and Main Bank
  (1010). Both accounting create and approve permissions are required.
- Record a signed bank/cash statement amount. Match one unused posted journal item
  on the same account and signed amount. Matching creates no extra payment.
- Receivables/Payables → Match Open Items selects posted debit/credit AR/AP items
  with the same account and partner. Match partially or fully; invoices/payments
  retain the existing automatic matching behavior.
- Admin → Dashboard → Period Lock sets a posting cutoff or clears it. Current
  lock state is visible to accounting viewers; changes require Admin plus version
  checks. Existing period restrictions still apply to all financial/stock posting.

No bank transfer or email is sent by these screens. Corrections to matched entries,
commercial refunds, bank feeds and statutory reporting are outside this phase.

## Financial reports

SQL computes posted balances, opening balances, period debit/credit and cumulative
closing balances. The UI offers Trial Balance, General Ledger, Profit and Loss,
Balance Sheet and Cash Movements with date filters. Statement totals include all
company postings in scope; search/pagination filters the displayed detail rows only.
Drafts never enter financial totals. Balance-sheet accumulated earnings are through
the To date; net profit uses the selected period. General Ledger rows are paginated
and link to the journal details. Authorized users can export the current filtered
ledger page as CSV, with spreadsheet formula escaping.

Cash Movements is a signed cash/bank movement summary, including internal transfers;
it is not a statutory classified cash-flow statement. Aging uses the current state
of reconciliation, not a reconstructed historical settlement snapshot. Monetary
calculations and posting are server-side Decimal; browser totals are previews.

## API and permissions

Native endpoints are under `/api/finance`:

| Endpoint | Purpose |
| --- | --- |
| `GET /summary` | SQL financial totals and current lock |
| `GET /accounts` | Search/type-filtered chart and account choices |
| `GET /entries` | Paginated journal headers/totals; no line arrays |
| `GET /entries/<id>` | One journal, lines, current version/actions and permitted source link |
| `GET /reports` | SQL statement account rows and independent company summary |
| `GET /ledger` | Paginated posted ledger items |
| `GET /open-items` | Paginated open AR/AP items with account/partner/side filters |
| `GET /lines/<id>` | One versioned journal item |
| `GET /statements` | Paginated statement rows and match state |
| `GET /statements/<id>/candidates` | Only eligible unused posted matching items |
| `GET /period-lock` | Lock state and Admin capability |
| `GET /entries/<id>/print` | Authenticated escaped printable journal |
| `GET /ledger/export` | Current filtered page CSV |
| `POST /commands/<command>` | Validated, versioned/idempotent commands |

Commands: `account`, `journal`, `edit-journal`, `post`, `reverse`, `transfer`,
`statement`, `match-bank`, `reconcile`, `period-lock`. Fields are allowlisted.
Every command needs an actor-scoped request key. Changes to an existing journal,
matching targets and lock state need their current versions. Stale writes return
409; missing versions return 428. Matching changes open-item versions. Retried
commands use saved receipts and cannot create duplicate journals, payments/matches
or accounts; reusing a key for different payloads returns 409. Permissions are
rechecked before replay. The shared SQL transaction lock serializes writes and
all entries, matches, receipt metadata and audit events commit atomically.

All native finance reads require Accounting view and provide authorized company-wide
financial data. Create/edit/approve/export are separate grants; Finance has these
by default, while ordinary Sales/HR/Viewer roles have no implied Accounting access.
Export/print requires export permission. The existing `/api/erp` API remains for
unconverted modules and compatibility; it does not acquire the native command
version/idempotency contract. No ownership or role rewrite is performed.

Lists default to 25 rows and cap at 100. Header reads avoid loading journal line
relationships. Reports aggregate in SQL and page ledger/account output. Server
queries still need measured load/index tuning before large-scale readiness can be
claimed; bounded browser reads alone are not a production capacity test.

## Existing desktop/database upgrade

Back up the database and stop workers first. Replace application files while
preserving `instance`, environment/database settings and the virtual environment.
From the project folder in Windows CMD:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app run --host 127.0.0.1 --port 5000
```

`init-db` adds `finance_command` for command receipts; existing accounts,
journals/lines, reconciliation and bank rows stay in their existing relational
tables. There is no ledger rewrite, reseeding or replay of postings. The storage
migration remains safe to repeat and upgrades older master/trade/HR releases if
needed. Keep your administrator; do not recreate it. Frontend assets are compiled
and included, so desktop ZIP users do not need Node. Hard-refresh after upgrade.

## Verification and remaining phases

Native backend simulations verify journal balance/post/edit/reverse, reports against
independent opening/period/cumulative calculations, SQL pagination without aggregate
materialization, idempotency/conflicts, scopes/export permissions, partial matching,
bank matching, locks and schema upgrade without reposting. DOM checks cover shared
navigation and native resource/read-model workflows. Chromium uses real forms for
accounts, draft validation/edit/post/reverse, transfers, statements, AR matching,
reports, printing, locks and mobile dialogs.

Inventory, Manufacturing, Expenses and administration still need their native content
conversion. Their relational services and automatic postings remain in place. Full
cross-browser, production deployment, load acceptance and Pakistan statutory tax/
payroll localization remain separate work.
