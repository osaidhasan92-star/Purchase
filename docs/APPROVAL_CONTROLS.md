# Independent approvals and PKR authority limits

## Upgrade and first setup

This release adds `approval_policy` and `approval_request`, including source-state,
inbox, idempotency and routing indexes. Stop workers and back up the database. With
the existing Python environment activated, run from the repository root:

```bat
python -m flask --app backend.app migrate-storage
```

Restart the backend and hard-refresh the browser. The migration creates the approval
tables without rewriting documents or replaying stock, payroll or accounting postings.
Existing installations retain their accounts, sessions, attachments and ledger history.

Approval enforcement is **on by default**, including for Admin. Limits deliberately
start unconfigured; no financial authority amounts are invented. Before demonstrating
controlled posting:

1. In Users & Roles, provide another active approver account and the relevant module
   view/approval permissions. Configure team manager links for staff where appropriate.
2. Open **Pending Approvals → Approval Controls** as Admin. Set the maximum PKR amount
   each approving role may authorize per operation. Record the policy change reason.
3. A blank role limit grants no approval authority. Zero permits only zero-value
   operations. Limits do not grant module permissions or company/team visibility.
4. Use separate accounts to request and approve a sample purchase, adjustment or payment.
   A single Admin cannot approve their own business request.

The creator of the source record and the submitter of a new posting request are both
excluded from approval. If those are different people, a third eligible reviewer may
be required. Linked employee users are also excluded from their own HR approvals.
Payroll payment and expense reimbursement reviewers need Accounting approval in
addition to the relevant HR/Expenses authority. Immediate command reviewers retain
the original endpoint's create/edit requirements; configuring a limit never adds rights.

## Request and decision flow

Creating/editing drafts and submitting documents for review retain their existing
screens. The inbox discovers supported review-state documents when opened or when
**Check for requests** is selected. Discovery uses SQL source/team scopes and checks
up to 100 unseen documents per register per refresh. Unknown historical creators are
not guessed; attributable records continue to load while unresolved records require
reviewed administrative correction.

Direct payments, stock adjustments/returns/scrap, internal transfers and actual
manufacturing completion first create a pending request. They return HTTP 202 and the
UI opens that request in the shared ERP workspace. No stock, payment or journal is
posted by submission. Frozen command inputs, source versions and human-readable
supporting details are stored for review; account/login/password endpoints are excluded.

Existing document approvals also require independent review. A permitted independent
reviewer can act from the module with an explicit `approvalReason`, or use the inbox.
Module buttons without a reason open the pending request for confirmation. Rejection
buttons open the shared reason dialog. Inbox decisions and policy changes require a
nonempty reason, up to 500 characters.

Routing tries the submitter's management chain, then bounded eligible active users and
Admins. Every candidate still needs a sufficient configured limit and the original
source-record permissions. Assignment sends no email or external message. Requests
without an eligible reviewer stay Pending and explicitly say so. Changing limits
prioritizes pending requests for routing review; refresh rechecks up to 100 existing
requests, rotating by last-routing time. Role/session/source/limit changes are checked
again when deciding, regardless of the stored assignment.

Approve executes the existing native, versioned, idempotent command as the reviewer.
The approval marker, audit reason and economic effects participate in the same native
transaction. Stale versions, changed permissions, period locks, insufficient stock or
invalid business transitions roll back the decision and its effects. Source/requester
attribution is preserved; the actual reviewer remains the audit actor. Repeated
submissions/decisions cannot duplicate posting or rewrite an existing decision reason.

Reject records the reason and uses the existing rejection, return-to-draft or
cancellation transition where supported. Rejected payroll/manual-journal drafts stay
editable; revise and request review again. Requests without a business record, such
as a proposed adjustment or payment, are simply declined without posting.

## Covered amounts and workflows

| Workflow | Approval amount / control |
| --- | --- |
| Purchase requests, vendor awards, POs, Sales quotation approvals | Full document amount, including configured tax/discount totals |
| Invoice/bill Finance posting and order-remainder closure | Full source document amount; existing Finance and order approval permissions remain required |
| Customer/supplier payments | Requested payment amount; always a separate pending request |
| Expense approval / reimbursement | Claim amount plus tax; reimbursement is a separate pending request |
| Payroll approval / payment | Gross salary on approval; net pay on payment; linked beneficiary cannot approve |
| Other supported HR approval transitions | Zero-value authority plus existing HR permissions and source scope |
| Stock adjustments, scrap, source returns | Absolute movement value at the applicable original/current costing basis |
| Manufacturing approval and actual completion | Planned/current material and conversion estimate; submitted actual consumption, scrap and conversion cost for actuals |
| Internal location transfers | Quantity at current company-average cost, even though no journal is created |
| Manual journal posting/reversal | Sum of debits in the source journal |
| Cash/bank transfers, reconciliation, bank matching | Requested transfer/match amount or absolute statement amount |
| Credit posting / applications / refunds | Credit amount on posting; requested settlement amount otherwise |
| Period locks | Zero-value authority and Admin restriction, with independent review |

These are per-operation limits, not cumulative budgets, purchase splitting detection,
foreign-currency exposure controls or multi-stage approval bands. Normal fulfillment
of already approved orders continues through existing quantity, reservation, warehouse
and posting controls. Draft edits and approved-order receipt/delivery operations retain
their resource-lock paths. Approval decisions and policy/routing control writes retain
the exclusive compatibility gate; this is not a claim of fully parallel financial posting.

## Visibility, audit and compatibility

The inbox shows the user's own requests and assigned reviews only where current
source/module visibility permits. Admin can inspect all requests but still has no
self-approval or amount-limit exception. Finance payment requests use the source
invoice's scope, rather than a payment record that does not yet exist. Restricted
reviewers lose inbox access when their role/source access is revoked. Request payloads
are not exposed as executable endpoints; reviewer actions use the stored allowlisted
operation and current server calculations. Credentials are rejected recursively from
business approval payloads and review snapshots.

Approval requests, approvals, rejections, reasons, actual actors and policy edits are
recorded in audit history. Business payloads remain frozen. No financial authority is
implied merely by assigning a manager or editing a role label.

Legacy aggregate writes, older ERP mutation routes, web imports and demo seeding are
blocked while enforcement is enabled so they cannot bypass the controls. Read-only
legacy adapters remain available. Reviewed initial data preparation and historical
attribution are separate administrative activities.

`APPROVAL_CONTROLS_ENABLED=false` is an explicit compatibility switch for isolated
historical workflow tests and service baselines; do not use it for a controlled
client/production environment. The old backend/browser workflow regressions set that
switch explicitly. Dedicated approval tests and the production-controls browser audit
run with enforcement enabled. The capacity probe identifies itself as a compatibility
baseline with approvals disabled; it does not measure this approval workflow's capacity.

## Verification

Run the normal backend tests and the dedicated controls suite:

```shell
python -m pytest backend/test_approvals.py -q
npm run test:approvals
```

The dedicated tests cover self-approval, missing/low limits, routing and policy edits,
source privacy, Finance payment scope, role revocation, payroll beneficiaries,
independent payments/reimbursements, manufacturing actuals, stock/location commands,
credit/refund posting, journal approval, stale rollback, concurrent reviewers,
rejection reasons, immutable decisions and upgrade preservation. The dedicated browser
audit uses two separate users with enforcement on, verifies no posting at submission,
independent execution, policy changes, shared rejection reasons and desktop/mobile Cancel.

PostgreSQL deployment behavior, sustained HTTP load, MFA/SSO, external notifications,
advanced approval chains and an independent security review remain separate acceptance
work. These controls do not establish full Odoo parity or enterprise readiness.
