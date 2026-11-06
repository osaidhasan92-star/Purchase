import { useEffect, useState, type ReactNode } from "react";
import type { Bridge, Workspace } from "../../types";
import { errorMessage } from "../../lib/api";
import {
  DashboardFrame,
  Kpi,
  Panel,
  Funnel,
  DashboardLink,
  money,
  Icon,
} from "./Dashboard";
export type ModuleKind =
  "overview" | "accounting" | "inventory" | "manufacturing" | "expenses" | "hr";
type Data = Record<string, unknown>;
type Item = Record<string, unknown>;
type Register = {
  key: string;
  count: number;
  statuses: Record<string, number>;
};
type Metric = { label: string; value: ReactNode; hint: string; icon: string };
const num = (value: unknown): number | undefined =>
  value === null ||
  value === undefined ||
  value === "" ||
  !Number.isFinite(Number(value))
    ? undefined
    : Number(value);
const text = (value: unknown) =>
  value === null || value === undefined ? "" : String(value);
const unavailable = <span className="ref-unavailable">Unavailable</span>;
const hrRoutes: Record<string, [string, string, string]> = {
  employees: ["Employees", "hr-employees", "hr_employees"],
  manpower: ["Manpower Requests", "hr-manpower", "hr_manpower"],
  candidates: ["Recruitment", "hr-recruitment", "hr_recruitment"],
  attendance: ["Attendance", "hr-attendance", "hr_attendance"],
  leaves: ["Leave Requests", "hr-leave", "hr_leave"],
  payroll: ["Payroll", "hr-payroll", "hr_payroll"],
  separations: ["Separations", "hr-separation", "hr_separation"],
};
function Distribution({
  rows,
  currency = false,
}: {
  rows: { label: string; value: number }[];
  currency?: boolean;
}) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.value)));
  return rows.length ? (
    <div
      className="ref-distribution"
      role="img"
      aria-label={rows
        .map((r) => r.label + ": " + (currency ? money(r.value) : r.value))
        .join("; ")}
    >
      {rows.map((r, i) => (
        <div className="ref-distribution-row" key={r.label}>
          <div>
            <span>{r.label}</span>
            <b>{currency ? money(r.value) : r.value.toLocaleString("en-PK")}</b>
          </div>
          <div className="ref-distribution-track">
            <span
              style={{
                width: (Math.abs(r.value) / max) * 100 + "%",
                background:
                  r.value < 0
                    ? "#dc7180"
                    : ["#16a3ac", "#7c64d8", "#e3a12d", "#387de0"][i % 4],
              }}
            />
          </div>
        </div>
      ))}
      {rows.some((r) => r.value < 0) && (
        <p className="hint">
          Bar lengths show absolute magnitude; labels retain their signs.
        </p>
      )}
    </div>
  ) : (
    <div
      className="ref-empty"
      role="img"
      aria-label="No data available to chart"
    >
      No data available for this view.
    </div>
  );
}
function Notes({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="ref-summary-list">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
export function ModuleDashboard({
  kind,
  summary,
  bridge,
  items = [],
  workspaces = [],
}: {
  kind: ModuleKind;
  summary: object;
  bridge: Bridge;
  items?: Item[];
  workspaces?: Workspace[];
}) {
  const s = summary as Data,
    states = (s.states || {}) as Record<string, number>,
    amounts = (s.amounts || {}) as Record<string, unknown>,
    registers = (s.registers || []) as Register[];
  const [recent, setRecent] = useState<Item[]>([]),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0);
  const hrRecent = Object.entries(hrRoutes).find(([, r]) => bridge.can(r[2]));
  const source =
    kind === "accounting"
      ? {
          path: "/finance/entries",
          permission: "accounting",
          view: "journals",
          title: "Recent Journal Entries",
        }
      : kind === "inventory"
        ? {
            path: "/inventory/movements",
            permission: "inventory",
            view: "stock-moves",
            title: "Recent Stock Movements",
          }
        : kind === "manufacturing"
          ? {
              path: "/production/orders",
              permission: "manufacturing",
              view: "production-orders",
              title: "Recent Manufacturing Orders",
            }
          : kind === "expenses"
            ? {
                path: "/expenses/claims",
                permission: "expenses",
                view: "expense-claims",
                title: "Recent Expense Claims",
              }
            : kind === "hr" && hrRecent
              ? {
                  path: "/hr/records/" + hrRecent[0],
                  permission: hrRecent[1][2],
                  view: hrRecent[1][1],
                  title: hrRecent[1][0] + " Snapshot",
                }
              : {
                  path: "/administration/activities",
                  permission: "activities",
                  view: "activities",
                  title: "Recent Activity",
                };
  const canRecent = bridge.can(source.permission);
  useEffect(() => {
    let active = true;
    setRecent([]);
    setError("");
    setLoading(canRecent);
    if (canRecent)
      bridge
        .request<{ items: Item[] }>(source.path + "?pageSize=5")
        .then((r) => {
          if (active) setRecent(r.items);
        })
        .catch((e) => {
          if (active) setError(errorMessage(e));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    return () => {
      active = false;
    };
  }, [bridge, kind, source.path, canRecent, summary, retry]);
  const metric = (
    label: string,
    key: string,
    hint: string,
    icon: string,
    currency = false,
  ): Metric => ({
    label,
    value:
      num(s[key]) === undefined
        ? unavailable
        : currency
          ? money(num(s[key])!)
          : num(s[key]),
    hint: num(s[key]) === undefined ? "Requires authorized data access" : hint,
    icon,
  });
  const count = (key: string, status?: string[]) => {
    const r = registers.find((r) => r.key === key);
    return r
      ? status
        ? status.reduce((n, v) => n + (r.statuses[v] || 0), 0)
        : r.count
      : undefined;
  };
  const hrMetric = (
    label: string,
    key: string,
    hint: string,
    status?: string[],
  ): Metric => ({
    label,
    value: count(key, status) ?? unavailable,
    hint:
      count(key, status) === undefined
        ? "Requires " + (hrRoutes[key]?.[0] || key) + " access"
        : hint,
    icon: key === "employees" ? "people" : "file",
  });
  let metrics: Metric[] = [],
    chartTitle = "",
    chartSubtitle = "",
    chartRows: { label: string; value: number }[] = [],
    currency = false,
    workflowTitle = "",
    workflowRows: { label: string; count: number }[] = [],
    lower: ReactNode[] = [],
    footer: ReactNode;
  const recordPanel = (
    <Panel
      key="recent"
      title={source.title}
      kicker="Latest records"
      subtitle="Up to five authorized records"
      action={
        canRecent ? (
          <DashboardLink href={"erp.html?view=" + source.view}>
            View records
          </DashboardLink>
        ) : undefined
      }
    >
      {!canRecent ? (
        <p className="ref-empty">
          Requires {source.permission.replaceAll("_", " ")} access.
        </p>
      ) : error ? (
        <p className="modern-error" role="alert">
          {error}{" "}
          <button type="button" onClick={() => setRetry((v) => v + 1)}>
            Try again
          </button>
        </p>
      ) : loading ? (
        <p className="ref-empty" role="status">
          Loading records…
        </p>
      ) : !recent.length ? (
        <p className="ref-empty">No records yet.</p>
      ) : (
        <div className="ref-recent">
          {recent.map((r, i) => (
            <a href={"erp.html?view=" + source.view} key={text(r.id) || i}>
              <div>
                <b>
                  {text(
                    r.number ||
                      r.name ||
                      r.employeeId ||
                      r.action ||
                      r.employee ||
                      r.id,
                  )}
                </b>
                <small>
                  {text(
                    r.product ||
                      r.description ||
                      r.memo ||
                      r.department ||
                      r.source ||
                      r.actor,
                  )}
                </small>
              </div>
              <div>
                <b>{text(r.status || r.state || r.kind)}</b>
                <small>
                  {text(r.date || r.month || r.at || r.joiningDate).slice(
                    0,
                    10,
                  )}
                </small>
              </div>
            </a>
          ))}
        </div>
      )}
    </Panel>
  );
  const quick = (title: string, rows: [string, string, string][]) => (
    <Panel
      key={title}
      title={title}
      kicker="Workspace"
      subtitle="Open an authorized register"
    >
      <div className="ref-quick-links">
        {rows
          .filter(([, , p]) => bridge.can(p))
          .map(([label, view]) => (
            <DashboardLink key={view} href={"erp.html?view=" + view}>
              {label}
              <span aria-hidden="true">→</span>
            </DashboardLink>
          ))}
        {!rows.some(([, , p]) => bridge.can(p)) && (
          <p className="ref-empty">No registers available for your role.</p>
        )}
      </div>
    </Panel>
  );
  if (kind === "accounting") {
    metrics = [
      metric("Cash & Bank", "cashBank", "Current posted balance", "cash", true),
      metric(
        "Receivables",
        "receivables",
        "Open customer position",
        "file",
        true,
      ),
      metric("Payables", "payables", "Open supplier position", "file", true),
      metric(
        "Net Profit",
        "profit",
        "Posted income less expenses",
        "chart",
        true,
      ),
    ];
    chartTitle = "Financial Position";
    chartSubtitle = "Current posted ledger balances · PKR";
    currency = true;
    chartRows = [
      ["Assets", "assets"],
      ["Liabilities", "liabilities"],
      ["Equity", "equity"],
      ["Current Earnings", "currentEarnings"],
    ].flatMap(([label, k]) =>
      num(s[k]) === undefined ? [] : [{ label, value: num(s[k])! }],
    );
    workflowTitle = "Cash Movement";
    lower = [
      recordPanel,
      <Panel
        key="controls"
        title="Accounting Controls"
        kicker="Integrity"
        subtitle="Posted ledger and period protection"
      >
        <Notes
          rows={[
            [
              "Accounting locked through",
              text((s.periodLock as Data)?.date) || "Not locked",
            ],
            [
              "Balance check",
              num(s.balanceCheck) === undefined
                ? unavailable
                : money(num(s.balanceCheck)!),
            ],
            ["Reporting through", text(s.toDate) || "All posted dates"],
          ]}
        />
        <p className="ref-panel-note">
          Accounting locked through:{" "}
          {text((s.periodLock as Data)?.date) || "Not locked"}. Balance check:
          PKR {text(s.balanceCheck)}.
        </p>
      </Panel>,
      quick("Accounting Workspace", [
        ["Journal Entries", "journals", "accounting"],
        ["Chart of Accounts", "accounts", "accounting"],
        ["Financial Reports", "reports", "accounting"],
        ["Receivables & Payables", "aged", "accounting"],
        ["Bank Reconciliation", "bank", "accounting"],
      ]),
    ];
  } else if (kind === "inventory") {
    metrics = [
      metric(
        "Stock Products",
        "stockProducts",
        "Stock-tracked product records",
        "order",
      ),
      metric(
        "Inventory Value",
        "inventoryValue",
        "Perpetual average-cost valuation",
        "cash",
        true,
      ),
      metric(
        "Stock Movements",
        "movements",
        "Recorded warehouse movements",
        "chart",
      ),
      {
        label: "Warehouse",
        value: text(s.warehouse) || unavailable,
        hint: "One company · one warehouse",
        icon: "order",
      },
    ];
    chartTitle = "Product Stock Values";
    chartSubtitle =
      "Top five stock values on the current product register page";
    currency = true;
    const stockItems = items.filter((r) => r.type === "stock");
    chartRows = stockItems
      .filter((r) => num(r.value) !== undefined)
      .sort((a, b) => Number(b.value) - Number(a.value))
      .slice(0, 5)
      .map((r) => ({ label: text(r.name), value: Number(r.value) }));
    workflowTitle = "Current Page Stock Mix";
    workflowRows = [
      {
        label: "Positive stock",
        count: stockItems.filter((r) => Number(r.quantity) > 0).length,
      },
      {
        label: "Zero stock",
        count: stockItems.filter((r) => num(r.quantity) === 0).length,
      },
      {
        label: "Negative stock",
        count: stockItems.filter((r) => (num(r.quantity) ?? 0) < 0).length,
      },
    ];
    lower = [
      recordPanel,
      <Panel
        key="valuation"
        title="Warehouse Controls"
        kicker="Valuation"
        subtitle="Posting rules"
      >
        <Notes
          rows={[
            ["Costing method", "Perpetual average cost"],
            ["Warehouse", text(s.warehouse)],
            ["Adjustments", "Posted movements with an audit trail"],
            ["Returns", "Linked to their original movement"],
          ]}
        />
      </Panel>,
      quick("Inventory Workspace", [
        ["Product Master", "products", "products"],
        ["Stock Balances", "inventory", "inventory"],
        ["Stock Movements", "stock-moves", "inventory"],
      ]),
    ];
  } else if (kind === "manufacturing") {
    const open =
      (states.Draft || 0) +
      (states.Confirmed || 0) +
      (states["In Progress"] || 0);
    metrics = [
      metric("Bills of Materials", "boms", "Defined product recipes", "file"),
      {
        label: "Open Orders",
        value: open,
        hint: "Draft, confirmed or in progress",
        icon: "order",
      },
      {
        label: "Completed Orders",
        value: states.Done || 0,
        hint: "Completed manufacturing orders",
        icon: "chart",
      },
      metric(
        "Completed Output Cost",
        "completedCost",
        "Actual cost of completed production",
        "cash",
        true,
      ),
    ];
    chartTitle = "Production Status";
    chartSubtitle = "Authorized manufacturing orders by current state";
    chartRows = Object.entries(states).map(([label, value]) => ({
      label,
      value,
    }));
    workflowTitle = "Production Workflow";
    workflowRows = [
      "Draft",
      "Confirmed",
      "In Progress",
      "Done",
      "Cancelled",
    ].map((label) => ({ label, count: states[label] || 0 }));
    lower = [
      recordPanel,
      <Panel
        key="rules"
        title="Material & Cost Controls"
        kicker="Production"
        subtitle="Standard manufacturing flow"
      >
        <Notes
          rows={[
            ["Bills of materials", text(s.boms)],
            ["Material availability", "Checked before production"],
            ["Consumption", "Components deducted on completion"],
            ["Output valuation", "Components plus conversion costs"],
          ]}
        />
      </Panel>,
      quick("Manufacturing Workspace", [
        ["Bills of Materials", "boms", "manufacturing"],
        ["Manufacturing Orders", "production-orders", "manufacturing"],
        ["Stock Movements", "stock-moves", "inventory"],
      ]),
    ];
  } else if (kind === "expenses") {
    metrics = [
      {
        label: "Draft Claims",
        value: states.Draft || 0,
        hint: "Claims being prepared",
        icon: "file",
      },
      {
        label: "Submitted Claims",
        value: states.Submitted || 0,
        hint: "Awaiting review",
        icon: "clock",
      },
      {
        label: "Approved Claims",
        value: states.Approved || 0,
        hint: "Awaiting reimbursement",
        icon: "order",
      },
      {
        label: "Reimbursed",
        value: money(num(amounts.Paid) ?? 0),
        hint: "Paid claim totals · PKR",
        icon: "cash",
      },
    ];
    chartTitle = "Expense Amounts by Status";
    chartSubtitle =
      "Authorized claim totals, including manually entered tax · PKR";
    currency = true;
    chartRows = ["Draft", "Submitted", "Approved", "Paid", "Rejected"].map(
      (label) => ({ label, value: num(amounts[label]) ?? 0 }),
    );
    workflowTitle = "Claim Workflow";
    workflowRows = ["Draft", "Submitted", "Approved", "Paid", "Rejected"].map(
      (label) => ({ label, count: states[label] || 0 }),
    );
    lower = [
      recordPanel,
      <Panel
        key="approvals"
        title="Approval Controls"
        kicker="Expenses"
        subtitle="Submit, review and reimburse"
      >
        <Notes
          rows={[
            ["Draft claims", "Do not post accounting entries"],
            ["On approval", "Expense and employee payable are posted"],
            ["On reimbursement", "Bank or cash clears the payable"],
            ["Visibility", "Your authorized claims and team scope"],
          ]}
        />
      </Panel>,
      quick("Expenses Workspace", [
        ["Expense Claims", "expense-claims", "expenses"],
        ["Journal Entries", "journals", "accounting"],
      ]),
    ];
  } else if (kind === "hr") {
    metrics = [
      hrMetric("Employees", "employees", "Employee register records"),
      hrMetric("Recruitment", "candidates", "Candidate register records"),
      hrMetric("Pending Leave", "leaves", "Awaiting a leave decision", [
        "Pending",
        "Pending Approval",
      ]),
      {
        label: "Paid Payroll",
        value:
          bridge.can("hr_payroll") && num(s.paidPayroll) !== undefined
            ? money(num(s.paidPayroll)!)
            : unavailable,
        hint: bridge.can("hr_payroll")
          ? "Recorded payroll payments · PKR"
          : "Requires Payroll access",
        icon: "cash",
      },
    ];
    chartTitle = "People Operations";
    chartSubtitle = "Authorized register totals · records, not unique people";
    chartRows = registers.map((r) => ({
      label: hrRoutes[r.key]?.[0] || r.key,
      value: r.count,
    }));
    workflowTitle = "Pending HR Decisions";
    workflowRows = registers.map((r) => ({
      label: hrRoutes[r.key]?.[0] || r.key,
      count: (r.statuses.Pending || 0) + (r.statuses["Pending Approval"] || 0),
    }));
    lower = [
      recordPanel,
      <Panel
        key="lifecycle"
        title="Employee Lifecycle"
        kicker="People"
        subtitle="Recruitment through payroll"
      >
        <Notes
          rows={[
            ["Onboarding", "Approved candidate → employee"],
            ["Attendance & Leave", "Recorded in their authorized registers"],
            ["Payroll", "Review → approve → record payment"],
            ["Posting", "Approved payroll posts automatically"],
          ]}
        />
      </Panel>,
      quick("HR Workspace", Object.values(hrRoutes)),
    ];
    footer = (
      <Panel
        title="Register Status Summary"
        kicker="HR reporting"
        subtitle="Counts follow your record permissions"
      >
        <div className="ref-register-grid">
          {registers.map((r) => (
            <a key={r.key} href={"erp.html?view=" + hrRoutes[r.key]?.[1]}>
              <b>{hrRoutes[r.key]?.[0] || r.key}</b>
              <strong>{r.count}</strong>
              <small>
                {Object.entries(r.statuses)
                  .map(([status, n]) => status + ": " + n)
                  .join(" · ")}
              </small>
            </a>
          ))}
        </div>
      </Panel>
    );
  } else {
    metrics = [
      metric("Cash & Bank", "cashBank", "Posted company balance", "cash", true),
      metric(
        "Inventory Value",
        "inventoryValue",
        "Current stock valuation",
        "order",
        true,
      ),
      metric(
        "Open Production",
        "openProduction",
        "Active manufacturing orders",
        "chart",
      ),
      metric(
        "Net Profit",
        "profit",
        "Posted income less expenses",
        "cash",
        true,
      ),
    ];
    chartTitle = "Operational Snapshot";
    chartSubtitle = "Authorized open work · current counts";
    chartRows = [
      ["Open Production", "openProduction"],
      ["Pending Expenses", "pendingExpenses"],
    ].flatMap(([label, k]) =>
      num(s[k]) === undefined ? [] : [{ label, value: num(s[k])! }],
    );
    workflowTitle = "Company Position";
    const groups: [string, string[]][] = [
      ["Customer Operations", ["crm", "sales", "purchase"]],
      ["Business Operations", ["inventory", "manufacturing", "expenses"]],
      ["People & Control", ["hr", "accounting", "admin"]],
    ];
    lower = groups.map(([title, ids]) => (
      <Panel
        key={title}
        title={title}
        kicker="Modules"
        subtitle="Your available workspaces"
      >
        <div className="ref-workspace-links">
          {workspaces
            .filter((w) => ids.includes(w.id))
            .map((w) => (
              <a key={w.id} href={w.href}>
                <Icon kind={w.id === "hr" ? "people" : "order"} />
                <div>
                  <b>{w.label}</b>
                  <small>Open {w.label} workspace</small>
                </div>
                <span aria-hidden="true">→</span>
              </a>
            ))}
          {!workspaces.some((w) => ids.includes(w.id)) && (
            <p className="ref-empty">No available modules for your role.</p>
          )}
        </div>
      </Panel>
    ));
    footer = recordPanel;
  }
  return (
    <DashboardFrame module={kind}>
      <div className="ref-kpis">
        {metrics.map((m, i) => (
          <Kpi
            key={m.label}
            {...m}
            tone={["teal", "violet", "amber", "blue"][i]}
          />
        ))}
      </div>
      <div className="ref-main-grid">
        <Panel
          title={chartTitle}
          kicker={kind === "accounting" ? "Financial snapshot" : "Performance"}
          subtitle={chartSubtitle}
        >
          <Distribution rows={chartRows} currency={currency} />
        </Panel>
        <Panel
          title={workflowTitle}
          kicker="Current position"
          subtitle={
            kind === "inventory"
              ? "Counts reflect the products on this page"
              : "Authorized operational information"
          }
        >
          {kind === "accounting" ? (
            <Notes
              rows={[
                [
                  "Cash In",
                  num(s.cashIn) === undefined
                    ? unavailable
                    : money(num(s.cashIn)!),
                ],
                [
                  "Cash Out",
                  num(s.cashOut) === undefined
                    ? unavailable
                    : money(num(s.cashOut)!),
                ],
                [
                  "Opening Cash",
                  num(s.openingCash) === undefined
                    ? unavailable
                    : money(num(s.openingCash)!),
                ],
                [
                  "Closing Cash",
                  num(s.closingCash) === undefined
                    ? unavailable
                    : money(num(s.closingCash)!),
                ],
              ]}
            />
          ) : kind === "overview" ? (
            <Notes
              rows={[
                [
                  "Receivables",
                  num(s.receivables) === undefined
                    ? unavailable
                    : money(num(s.receivables)!),
                ],
                [
                  "Payables",
                  num(s.payables) === undefined
                    ? unavailable
                    : money(num(s.payables)!),
                ],
                ["Pending Expenses", num(s.pendingExpenses) ?? unavailable],
                ["Warehouse", text(s.warehouse) || "WH / Stock"],
              ]}
            />
          ) : (
            <Funnel rows={workflowRows} />
          )}
        </Panel>
      </div>
      <div className="ref-three-grid">{lower}</div>
      {footer}
    </DashboardFrame>
  );
}
