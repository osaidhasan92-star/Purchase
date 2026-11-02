import { useEffect, useState } from "react";
import type { Bridge } from "../../types";
import { errorMessage } from "../../lib/api";
import {
  Kpi,
  Panel,
  Trend,
  Funnel,
  Health,
  DashboardLink,
  money,
} from "../../components/dashboard/Dashboard";
import { configs, route, type Resource } from "./types";
interface Register {
  key: Resource;
  count: number;
  total: number;
  statuses: Record<string, number>;
}
interface Recent {
  id: string | number;
  number: string;
  date: string;
  partner: string;
  status: string;
  total: number;
}
interface Summary {
  registers: Register[];
  trend: { month: string; value: number }[];
  recent: Record<string, Recent[]>;
  balances: { outstanding?: number; collected?: number };
  partners: number | null;
}
export function TradeDashboard({
  bridge,
  area,
}: {
  bridge: Bridge;
  area: "sales" | "purchase";
}) {
  const [data, setData] = useState<Summary | null>(null),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    bridge
      .request<Summary>("/trade/summary/" + area)
      .then((r) => {
        if (active) setData(r);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [area, bridge, reload]);
  const sales = area === "sales",
    orderKey = sales ? "salesOrders" : "orders",
    invoiceKey = sales ? "customerInvoices" : "invoices",
    paymentKey = sales ? "customerPayments" : "payments";
  const reg = (key: Resource) => data?.registers.find((r) => r.key === key);
  const count = (key: Resource, statuses?: string[]) => {
    const r = reg(key);
    return r
      ? statuses
        ? statuses.reduce((n, s) => n + (r.statuses[s] || 0), 0)
        : r.count
      : 0;
  };
  const has = (key: Resource) => !!reg(key);
  const pending = count(sales ? "salesQuotations" : "requests", [
    "Pending Approval",
  ]);
  const open = count(
    orderKey,
    sales
      ? ["Confirmed", "Partially Delivered"]
      : [
          "Draft",
          "Pending Approval",
          "Approved",
          "Sent to Vendor",
          "Partially Received",
        ],
  );
  const unpaid = count(
    invoiceKey,
    sales ? ["Posted", "Partially Paid"] : ["Approved", "Partially Paid"],
  );
  const recentKey = sales ? orderKey : "requests";
  const recent = (key: Resource, empty: string) =>
    !data?.recent[key]?.length ? (
      <p className="ref-empty">{empty}</p>
    ) : (
      <div className="ref-recent">
        {data.recent[key].map((r) => (
          <a
            key={r.id}
            href={route(key) + "&search=" + encodeURIComponent(r.number)}
          >
            <div>
              <b>{r.number}</b>
              <small>{r.partner || r.date}</small>
            </div>
            <div>
              <b>{money(r.total)}</b>
              <small>{r.status}</small>
            </div>
          </a>
        ))}
      </div>
    );
  const funnel = sales
    ? (has("salesQuotations")
        ? ["Draft", "Pending Approval", "Approved", "Sent", "Accepted"]
        : []
      ).map((s) => ({ label: s, count: count("salesQuotations", [s]) }))
    : [
        { label: "Requests", count: count("requests") },
        { label: "RFQs", count: count("rfqs") },
        { label: "Vendor Quotes", count: count("quotations") },
        { label: "Purchase Orders", count: count("orders") },
      ].filter((_, i) =>
        has((["requests", "rfqs", "quotations", "orders"] as Resource[])[i]),
      );
  return (
    <section
      className="reference-dashboard trade-reference-dashboard"
      data-screen={"trade-" + area + "-dashboard-react"}
      aria-busy={!data && !error}
    >
      {error && (
        <p className="modern-error" role="alert">
          {error}{" "}
          <button type="button" onClick={() => setReload((v) => v + 1)}>
            Try again
          </button>
        </p>
      )}
      {!data ? (
        <p aria-busy={!error}>Loading dashboard…</p>
      ) : (
        <div aria-busy="false">
          <div className="ref-kpis">
            <Kpi
              label={sales ? "Sales Order Value" : "Purchase Spend"}
              value={has(orderKey) ? money(reg(orderKey)?.total || 0) : "—"}
              hint={
                sales
                  ? "Total recorded order value"
                  : "Total purchase order value"
              }
              icon="cash"
            />
            <Kpi
              label={sales ? "Open Orders" : "Pending Approval"}
              value={
                sales
                  ? has(orderKey)
                    ? open
                    : "—"
                  : has("requests")
                    ? pending
                    : "—"
              }
              hint={
                sales
                  ? "Orders still in fulfillment"
                  : "Requests awaiting action"
              }
              tone="violet"
              icon={sales ? "order" : "clock"}
            />
            <Kpi
              label={sales ? "Collected" : "Open Orders"}
              value={
                sales
                  ? has(paymentKey)
                    ? money(data.balances.collected || 0)
                    : "—"
                  : has(orderKey)
                    ? open
                    : "—"
              }
              hint={
                sales ? "Customer payments received" : "Orders still active"
              }
              tone="green"
              icon={sales ? "cash" : "order"}
            />
            <Kpi
              label={sales ? "Receivables" : "Payables"}
              value={
                has(invoiceKey) ? money(data.balances.outstanding || 0) : "—"
              }
              hint={
                sales
                  ? "Outstanding posted invoices"
                  : "Outstanding approved bills"
              }
              tone="amber"
              icon="file"
            />
          </div>
          <div className="ref-main-grid">
            <Panel
              title={sales ? "Sales Order Trend" : "Purchase Order Trend"}
              kicker={sales ? "Performance" : "Procurement spend"}
              subtitle="Confirmed order value over the last six months"
              action={
                <span className="ref-badge">
                  {money(data.trend.reduce((n, r) => n + r.value, 0))} total
                </span>
              }
            >
              {has(orderKey) ? (
                <Trend
                  rows={data.trend}
                  color={sales ? "#232e78" : "#95a5bf"}
                  title={
                    (sales ? "Sales" : "Purchase") +
                    " confirmed order value by month"
                  }
                />
              ) : (
                <p className="ref-empty">
                  Order reporting is not available for your role.
                </p>
              )}
            </Panel>
            <Panel
              title={sales ? "Quote Progress" : "Procurement Funnel"}
              kicker={sales ? "Quotation funnel" : "Sourcing pipeline"}
              subtitle={
                sales
                  ? "From draft to customer acceptance"
                  : "Volumes by purchasing stage"
              }
              action={
                <span className="ref-badge">
                  {count(sales ? "salesQuotations" : "requests")}
                </span>
              }
            >
              {funnel.length ? (
                <Funnel rows={funnel} color={sales ? "#39bca2" : "#7876cf"} />
              ) : (
                <p className="ref-empty">No permitted pipeline registers.</p>
              )}
              <div className="ref-panel-foot">
                {sales
                  ? `${count("salesQuotations", ["Accepted"])} accepted · ${count("salesQuotations", ["Rejected"])} rejected`
                  : `${count("quotations")} vendor quotations · ${count("orders")} purchase orders`}
              </div>
            </Panel>
          </div>
          <div className="ref-three-grid">
            <Panel
              title={sales ? "Sales Health" : "Procurement Health"}
              kicker="Operations"
              subtitle="Live work in progress"
            >
              <Health
                rows={[
                  ...(has(orderKey)
                    ? [{ label: "Open Orders", value: open, icon: "order" }]
                    : []),
                  ...(has(sales ? "deliveries" : "requests")
                    ? [
                        {
                          label: sales
                            ? "Pending Deliveries"
                            : "Pending Approvals",
                          value: sales
                            ? count("deliveries", ["Pending"])
                            : pending,
                          icon: "clock",
                        },
                      ]
                    : []),
                  ...(has(invoiceKey)
                    ? [
                        {
                          label:
                            unpaid + "" === "1"
                              ? "Unpaid Invoice"
                              : "Unpaid Invoices",
                          value: unpaid,
                          icon: "file",
                        },
                      ]
                    : []),
                  ...(has(paymentKey)
                    ? [
                        {
                          label: sales ? "Payments Received" : "Goods Receipts",
                          value: count(sales ? "customerPayments" : "receipts"),
                          icon: "cash",
                        },
                      ]
                    : []),
                ]}
              />
            </Panel>
            <Panel
              title={sales ? "Recent Orders" : "Recent Purchase Requests"}
              kicker={sales ? "Orders" : "Requests"}
              subtitle={
                sales ? "Most recent order values" : "Latest internal demand"
              }
              action={
                has(recentKey) ? (
                  <DashboardLink href={route(recentKey)}>
                    {sales ? "View orders" : "View requests"}
                  </DashboardLink>
                ) : undefined
              }
            >
              {recent(
                recentKey,
                sales ? "No sales orders yet." : "No purchase requests yet.",
              )}
            </Panel>
            <Panel
              title={sales ? "Delivery Status" : "Supplier Overview"}
              kicker={sales ? "Fulfillment" : "Suppliers"}
              subtitle={
                sales
                  ? "Customer orders in dispatch"
                  : "Vendor and invoice position"
              }
              action={
                !sales && bridge.can("vendors") ? (
                  <DashboardLink href="erp.html?view=vendors&module=purchase">
                    View vendors
                  </DashboardLink>
                ) : sales && has("deliveries") ? (
                  <DashboardLink href={route("deliveries")}>
                    Deliveries
                  </DashboardLink>
                ) : undefined
              }
            >
              <Health
                rows={
                  sales
                    ? [
                        ...(has("deliveries")
                          ? [
                              {
                                label: "Total deliveries",
                                value: count("deliveries"),
                                icon: "order",
                              },
                              {
                                label: "Dispatched",
                                value: count("deliveries", [
                                  "Dispatched",
                                  "Delivered",
                                ]),
                                icon: "chart",
                              },
                              {
                                label: "Pending",
                                value: count("deliveries", ["Pending"]),
                                icon: "clock",
                              },
                            ]
                          : []),
                        ...(has(invoiceKey)
                          ? [
                              {
                                label: "Invoices unpaid",
                                value: unpaid,
                                icon: "file",
                              },
                            ]
                          : []),
                      ]
                    : [
                        ...(data.partners !== null
                          ? [
                              {
                                label: "Vendors",
                                value: data.partners,
                                icon: "people",
                              },
                            ]
                          : []),
                        ...(has("quotations")
                          ? [
                              {
                                label: "Vendor quotes",
                                value: count("quotations"),
                                icon: "file",
                              },
                            ]
                          : []),
                        ...(has(invoiceKey)
                          ? [
                              {
                                label: "Unpaid invoices",
                                value: unpaid,
                                icon: "file",
                              },
                            ]
                          : []),
                        ...(has("receipts")
                          ? [
                              {
                                label: "Goods receipts",
                                value: count("receipts"),
                                icon: "order",
                              },
                            ]
                          : []),
                      ]
                }
              />
            </Panel>
          </div>
          <Panel
            title={
              sales ? "Recent Customer Invoices" : "Open Supplier Balances"
            }
            kicker={sales ? "Collections" : "Payables"}
            subtitle={
              sales
                ? "Track customer billing and collections"
                : "Approved bills awaiting supplier payment"
            }
            action={
              has(invoiceKey) ? (
                <DashboardLink href={route(invoiceKey)}>
                  View invoices
                </DashboardLink>
              ) : undefined
            }
          >
            {sales ? (
              recent(invoiceKey, "No customer invoices yet.")
            ) : (
              <div className="ref-finance-strip">
                <div>
                  <small>Outstanding supplier balance</small>
                  <b>
                    {has(invoiceKey)
                      ? money(data.balances.outstanding || 0)
                      : "—"}
                  </b>
                </div>
                <div>
                  <small>Supplier payments processed</small>
                  <b>
                    {has(paymentKey)
                      ? money(data.balances.collected || 0)
                      : "—"}
                  </b>
                </div>
              </div>
            )}
          </Panel>
          <details className="ref-registers">
            <summary>Document registers and recorded values</summary>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Register</th>
                    <th>Documents</th>
                    <th>Recorded Value (PKR)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.registers.map((r) => (
                    <tr key={r.key}>
                      <td>
                        <a href={route(r.key)}>{configs[r.key].label}</a>
                      </td>
                      <td>{r.count}</td>
                      <td>{money(r.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint">
              Recorded values include all document statuses. Use Accounting for
              posted financial statements.
            </p>
          </details>
        </div>
      )}
    </section>
  );
}
