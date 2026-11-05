import type { Bridge, User } from "../../types";
import {
  DashboardFrame,
  Kpi,
  Panel,
  Trend,
  Icon,
  money,
  DashboardLink,
} from "../../components/dashboard/Dashboard";
import type { Summary } from "./types";
export interface AccountingData extends Summary {
  trend: { month: string; income: string; expenses: string }[];
  banking: {
    bank: string;
    cash: string;
    unmatched: number;
    unmatchedReceipts: string;
    unmatchedPayments: string;
    paymentPosting: string;
  };
  customerInvoices: InvoiceCounts | null;
  vendorBills: InvoiceCounts | null;
  recent: {
    id: string | number;
    key: string;
    number: string;
    date: string;
    partner: string;
    amount: string;
    documentStatus: string;
    paymentStatus: string;
  }[];
}
interface InvoiceCounts {
  draft: number;
  unpaid: number;
  partial: number;
  paid: number;
  total: number;
}
const href = (view: string, extra: Record<string, string> = {}) =>
  "erp.html?" + new URLSearchParams({ view, module: "accounting", ...extra });
export function AccountingDashboard({
  data,
  bridge,
  user,
  period,
  onPeriod,
  onTransfer,
  onLock,
}: {
  data: AccountingData;
  bridge: Bridge;
  user: User;
  period: string;
  onPeriod: (value: string) => void;
  onTransfer: () => void;
  onLock: () => void;
}) {
  const values = [
    ["Cash & Bank", "cashBank", "cash"],
    ["Receivables", "receivables", "people"],
    ["Payables", "payables", "file"],
    ["Net Profit", "profit", "chart"],
  ];
  const metric = (key: string) =>
    typeof data[key] === "string" && Number.isFinite(Number(data[key])) ? (
      money(Number(data[key]))
    ) : (
      <span className="ref-unavailable">Unavailable</span>
    );
  const block = (
    title: string,
    counts: InvoiceCounts | null,
    view: string,
    icon: string,
  ) => (
    <Panel
      title={title}
      action={<Icon kind={icon} />}
      subtitle="Documents dated in the selected period"
    >
      <div className="acct-invoice-counts">
        {counts ? (
          [
            ["Draft", counts.draft, "draft"],
            [
              title === "Customer Invoices"
                ? "Posted / Unpaid"
                : "Awaiting Payment",
              counts.unpaid,
              "open",
            ],
            ["Partially Paid", counts.partial, "partial"],
            ["Paid", counts.paid, "paid"],
          ].map(([label, n, state]) => (
            <a
              key={label}
              href={href(view, {
                from: String(data.fromDate || ""),
                to: String(data.toDate),
                status:
                  label === "Draft"
                    ? title === "Vendor Bills"
                      ? "Draft|Matched"
                      : "Draft"
                    : label === "Partially Paid"
                      ? "Partially Paid"
                      : label === "Paid"
                        ? "Paid"
                        : title === "Customer Invoices"
                          ? "Posted"
                          : "Approved",
              })}
            >
              <span>{label}</span>
              <b className={"acct-count acct-" + state}>{n}</b>
            </a>
          ))
        ) : (
          <p className="ref-empty">
            Unavailable · Requires{" "}
            {title === "Customer Invoices" ? "customer invoice" : "vendor bill"}{" "}
            access.
          </p>
        )}
      </div>
      {counts && (
        <div className="acct-panel-link">
          <DashboardLink
            href={href(view, {
              from: String(data.fromDate || ""),
              to: String(data.toDate),
            })}
          >
            View {title === "Customer Invoices" ? "Invoices" : "Bills"}{" "}
            <span aria-hidden="true">→</span>
          </DashboardLink>
        </div>
      )}
    </Panel>
  );
  return (
    <DashboardFrame module="accounting">
      <div className="acct-toolbar">
        <label>
          <span className="sr-only">Accounting period</span>
          <select
            aria-label="Accounting period"
            value={period}
            onChange={(e) => onPeriod(e.target.value)}
          >
            <option value="month">This Month</option>
            <option value="quarter">This Quarter</option>
            <option value="year">This Year</option>
            <option value="all">All Time</option>
          </select>
        </label>
        <div>
          {bridge.can("sales_invoices") &&
            bridge.can("sales_invoices", "create") && (
              <a
                className="btn-primary acct-new-invoice"
                href={href("sales-invoices", { new: "1" })}
              >
                <span aria-hidden="true">＋</span> New Invoice
              </a>
            )}
          {bridge.can("invoices") && bridge.can("invoices", "create") && (
            <a
              className="btn-primary acct-new-bill"
              href={href("invoices", { new: "1" })}
            >
              <span aria-hidden="true">＋</span> New Bill
            </a>
          )}
        </div>
      </div>
      <div className="ref-kpis">
        {values.map(([label, key, icon], i) => (
          <Kpi
            key={key}
            label={label}
            value={metric(key)}
            hint={
              key === "profit"
                ? "Posted income less expenses in period"
                : "Posted balance as of " + data.toDate
            }
            icon={icon}
            tone={["teal", "violet", "amber", "blue"][i]}
          />
        ))}
      </div>
      <div className="ref-main-grid acct-main-grid">
        <Panel
          title="Financial Overview"
          subtitle="Posted income and expenses · six months ending the selected date"
        >
          <Trend
            rows={data.trend.map((r) => ({
              month: r.month,
              value: Number(r.income),
              second: Number(r.expenses),
            }))}
            secondary
            color="#099d92"
            secondaryColor="#8554de"
            showScale
            title="Monthly posted income and expenses in PKR"
          />
          <div className="acct-chart-legend">
            <span>
              <i />
              Income (PKR)
            </span>
            <span>
              <i />
              Expenses (PKR)
            </span>
          </div>
        </Panel>
        <Panel
          title="Banking & Reconciliation"
          subtitle={"Bank and cash balances as of " + data.toDate}
        >
          <div className="acct-bank-balances">
            <div>
              <Icon kind="cash" />
              <span>
                Bank Balance<strong>{money(Number(data.banking.bank))}</strong>
              </span>
            </div>
            <div>
              <Icon kind="cash" />
              <span>
                Cash Balance<strong>{money(Number(data.banking.cash))}</strong>
              </span>
            </div>
          </div>
          <div
            className={
              "acct-unmatched" +
              (data.banking.unmatched === 0 ? " acct-matched-clear" : "")
            }
          >
            <span>
              <Icon kind="clock" />
              <b>{data.banking.unmatched} unmatched transactions</b>
            </span>
            <a
              href={href("bank", {
                status: "Unmatched",
                from: String(data.fromDate || ""),
                to: String(data.toDate),
              })}
            >
              Reconcile Transactions
            </a>
          </div>
          <dl className="acct-banking-totals">
            <div>
              <dt>Unmatched receipts</dt>
              <dd>{money(Number(data.banking.unmatchedReceipts))}</dd>
            </div>
            <div>
              <dt>Unmatched payments</dt>
              <dd>{money(Number(data.banking.unmatchedPayments))}</dd>
            </div>
          </dl>
          <p className="acct-bank-note">
            Unmatched transactions are within the selected period. Payments post
            directly to bank/cash; bank matching is tracked separately.
          </p>
        </Panel>
      </div>
      <div className="ref-three-grid acct-three-grid">
        {block(
          "Customer Invoices",
          data.customerInvoices,
          "sales-invoices",
          "file",
        )}
        {block("Vendor Bills", data.vendorBills, "invoices", "file")}
        <Panel
          title="Financial Reports"
          action={<Icon kind="chart" />}
          subtitle="Posted financial records"
        >
          <div className="acct-report-links">
            {[
              ["Profit & Loss", "reports", { report: "pnl" }],
              ["Balance Sheet", "reports", { report: "balance" }],
              ["General Ledger", "reports", { report: "ledger" }],
              ["Aged Receivables", "aged", { account: "1100" }],
              ["Aged Payables", "aged", { account: "2100" }],
            ].map(([label, view, extra]) => (
              <a
                key={String(label)}
                href={href(String(view), {
                  ...(extra as Record<string, string>),
                  from: view === "reports" ? String(data.fromDate || "") : "",
                  to: String(data.toDate),
                })}
              >
                <Icon kind={label === "General Ledger" ? "file" : "chart"} />
                <span>{String(label)}</span>
                <span aria-hidden="true">→</span>
              </a>
            ))}
          </div>
        </Panel>
      </div>
      <Panel
        title="Recent Transactions"
        subtitle="Latest authorized customer invoices and vendor bills in the selected period"
      >
        <div className="acct-transactions-wrap">
          <table className="acct-transactions">
            <thead>
              <tr>
                {[
                  "Date",
                  "Document",
                  "Partner",
                  "Amount",
                  "Document Status",
                  "Payment Status",
                ].map((t) => (
                  <th key={t}>{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.recent.map((r) => (
                <tr key={r.key + ":" + r.id}>
                  <td>{r.date}</td>
                  <td>
                    <a
                      href={href(
                        r.key === "customerInvoices"
                          ? "sales-invoices"
                          : "invoices",
                        { search: r.number },
                      )}
                    >
                      {r.number}
                    </a>
                  </td>
                  <td>{r.partner}</td>
                  <td>{money(Number(r.amount))}</td>
                  <td>
                    <span
                      className={
                        "acct-state " +
                        (r.documentStatus === "Posted"
                          ? "acct-posted"
                          : "acct-draft")
                      }
                    >
                      {r.documentStatus}
                    </span>
                  </td>
                  <td>
                    <span
                      className={
                        "acct-state " +
                        (r.paymentStatus === "Paid"
                          ? "acct-paid"
                          : r.paymentStatus === "Partially Paid"
                            ? "acct-partial"
                            : "acct-open")
                      }
                    >
                      {r.paymentStatus}
                    </span>
                  </td>
                </tr>
              ))}
              {!data.recent.length && (
                <tr>
                  <td colSpan={6}>
                    {data.customerInvoices === null && data.vendorBills === null
                      ? "Invoice and bill access is required to view recent transactions."
                      : "No transactions in the selected period."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="acct-controls">
        <span>
          Accounting locked through:{" "}
          {String(data.periodLock.date || "Not locked")}. Balance check: PKR{" "}
          {Number(data.balanceCheck).toLocaleString("en-PK", {
            minimumFractionDigits: 2,
          })}
          .
        </span>
        <div>
          {bridge.can("accounting", "create") &&
            bridge.can("accounting", "approve") && (
              <button className="btn-secondary" onClick={onTransfer}>
                Bank / Cash Transfer
              </button>
            )}
          {user.role === "Admin" && (
            <button className="btn-secondary" onClick={onLock}>
              Period Lock
            </button>
          )}
        </div>
      </div>
    </DashboardFrame>
  );
}
