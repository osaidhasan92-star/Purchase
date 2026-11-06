# Approval limits and separation of duties

Financial controls are enabled by default. Run the normal migration before restarting workers:

```bash
python -m flask --app backend.app migrate-storage
```

This creates `approval` and `approval_limit` without rewriting existing business records. Restart all backend workers and refresh the browser with Ctrl+F5. The **Pending Approvals** button is available in every ERP workspace.

## Authority

| Role | Default maximum per action (PKR) |
| --- | ---: |
| Manager roles | 100,000.00 |
| Finance | 1,000,000.00 |
| Admin | 10,000,000.00 |
| Other roles | No approval authority |

These are starting configuration values, not a claim about the company's financial policy. Administrators can set a per-user, per-module override from **Pending Approvals → Approval limits**. Existing module approval permissions must also allow the action. A zero override permits only zero-value approvals. Negative, non-finite and fractional-cent limits are rejected. There is no unlimited administrator exemption.

A decision maker must differ from both the source creator and the user requesting the action. Every decision requires a reason. Legacy documents with unknown creators require attribution before approval. Source amounts and creators are read from server records. Higher-value requests appear to active users whose module permissions and current limits cover the value. A request with no eligible independent approver stays blocked; an administrator must configure authority or another account. Requests are not emailed or sent to external messaging services.

## Workflow

- Purchase requests/orders and sales quotations route on submission. Bills and invoices route on submission for posting.
- Expense claims and credit notes route on submission. Payroll, leave/manpower/separation requests and manufacturing orders route from creation to their initial approval.
- Payments/receipts, cash-bank transfers, manual journal posting/reversal, bank matching/reconciliation, period-lock changes, expense reimbursements, credit settlement/refunds, stock adjustment/scrap/returns, warehouse transfers and manufacturing completion queue when requested.
- Draft editing and ordinary operational steps retain their existing permissions and state rules. Manufacturing BoM creation, customer/CRM data entry, receiving and delivery are not themselves new financial signoffs.
- The original action returns `409` with an approval reference when queued; submission that automatically creates a request still returns `200`, with `approvalRequested`.
- Review source details in the shared inbox, enter a reason, and choose **Approve and execute** or **Reject**. The action runs as the decision maker, with existing module permissions, scope, current versions, stock checks and ledger checks enforced again.
- A rejection declines the queued action and records its reason. It leaves the source document in its existing state. Correct the source or reload and make a fresh request when appropriate.
- Approval and its financial posting share one transaction. Stale records, changed authority and business validation failures roll back execution and leave the request pending. Reload the source and submit a fresh request after correction. Duplicate decisions cannot execute twice.

The inbox supports status filters and pagination. It shows a server snapshot of the source plus the requested operation. Audit history records requests, approvals, rejections, decision makers, amounts, reasons and limit changes. Do not treat a decision as an actual external bank transfer: the application records accounting operations only.

Legacy `/api/erp/*` POST adapters are retired, except company-profile settings. Aggregate financial/HR PATCH adapters are blocked while approval controls are enabled. Native resource endpoints are the supported write path.

## Validation and rollout

`backend/test_approval_api.py` checks independent authority, exact limits, per-user configuration, reasons, CSRF, privacy, stale-source rollback, automatic routing, purchase/expense/payroll/inventory/manufacturing integration and concurrent decisions. `tests/approval-browser.cjs` checks the shared inbox, execution, history, limit settings and mobile layout with two independent accounts.

Historical workflow tests and the historical capacity probe explicitly disable the new gate to retain their original posting baseline. The capacity report states that exclusion; its results must not be used as throughput evidence for approvals. The new approval tests exercise the enabled policy. The browser workflow runs the new enabled-policy suite separately.

Before a large-company rollout, run sustained end-to-end load against PostgreSQL with approvals enabled and realistic data, HTTP and multiple workers. Include queue creation, inbox paging, high-value escalation, concurrent decisions, stale versions, and permission changes. Approval commands currently take the shared ERP lock for consistent policy/value reads; measure lock waits and queue latency at the target concurrency before raising throughput claims.

Monitor request latency/error rate, lock waits/retries, pending-approval count/oldest age, blocked routing, failed decisions, ledger/stock health and database capacity. Verify encrypted backup retention and perform an isolated restore drill with ledger balances, stock and approval/audit counts checked. Existing capacity, workflow-health and backup-verification tools remain starting points, not a production-readiness certification. No live infrastructure or production backup was tested as part of this change.
