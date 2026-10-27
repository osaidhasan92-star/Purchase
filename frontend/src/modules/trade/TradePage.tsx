import { useEffect, useRef, useState } from "react";
import type { Bridge, User } from "../../types";
import { Dialog } from "../../components/Dialog";
import { errorMessage } from "../../lib/api";
import { Reference } from "./Reference";
import { TradeForm } from "./TradeForm";
import {
  configs,
  economicLines,
  actionLabels,
  keyFor,
  money,
  str,
  route,
  type Resource,
  type Detail,
  type TradeRecord,
  type TradePageData,
} from "./types";
function nextSteps(
  resource: Resource,
  row: TradeRecord,
): { resource: Resource; label: string; sourceId: string | number }[] {
  const add = (target: Resource, label: string, sourceId = row.id) => [
    { resource: target, label, sourceId },
  ];
  if (resource === "requests" && row.status === "Approved")
    return add("rfqs", "Create RFQ");
  if (resource === "rfqs" && ["Sent", "Response Received"].includes(row.status))
    return add("quotations", "Record Vendor Quote");
  if (
    resource === "comparisons" &&
    row.status === "Completed" &&
    row.selectedQuotationId
  )
    return add("orders", "Create PO", str(row.selectedQuotationId));
  if (resource === "quotations" && row.status === "Selected")
    return add("orders", "Create PO");
  if (resource === "salesQuotations" && row.status === "Accepted")
    return add("salesOrders", "Create Sales Order");
  if (
    resource === "orders" &&
    ["Approved", "Sent to Vendor", "Partially Received", "Received"].includes(
      row.status,
    )
  )
    return [
      ...(row.status !== "Received" ? add("receipts", "Receive Goods") : []),
      ...add("invoices", "Record Bill"),
    ];
  if (
    resource === "salesOrders" &&
    ["Confirmed", "Partially Delivered", "Delivered"].includes(row.status)
  )
    return [
      ...(row.status !== "Delivered"
        ? add("deliveries", "Create Delivery")
        : []),
      ...add("customerInvoices", "Create Invoice"),
    ];
  if (
    resource === "invoices" &&
    ["Approved", "Partially Paid"].includes(row.status)
  )
    return add("payments", "Record Payment");
  if (
    resource === "customerInvoices" &&
    ["Posted", "Partially Paid"].includes(row.status)
  )
    return add("customerPayments", "Receive Payment");
  return [];
}
export function TradePage({
  resource,
  bridge,
  user,
}: {
  resource: Resource;
  bridge: Bridge;
  user: User;
}) {
  const config = configs[resource];
  const [data, setData] = useState<TradePageData>({
      items: [],
      total: 0,
      page: 1,
      pageSize: 25,
    }),
    [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState(""),
    [reload, setReload] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [form, setForm] = useState<{
      editing?: TradeRecord;
      sourceId?: string;
      leadId?: string;
    } | null>(null),
    [detail, setDetail] = useState<Detail | null>(null),
    [busy, setBusy] = useState(false),
    [opening, setOpening] = useState("");
  const actionKeys = useRef(new Map<string, string>()),
    active = useRef(true),
    actionBusy = useRef(false);
  useEffect(() => {
    active.current = true;
    const params = new URLSearchParams(location.search);
    if (
      bridge.can(config.module, "create") &&
      (params.has("sourceId") || params.has("leadId"))
    )
      setForm({
        sourceId: params.get("sourceId") || undefined,
        leadId: params.get("leadId") || undefined,
      });
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    bridge
      .request<TradePageData>(
        "/trade/" +
          resource +
          "?" +
          new URLSearchParams({
            page: String(page),
            pageSize: "25",
            search,
            status,
          }),
      )
      .then((result) => {
        if (alive) setData(result);
      })
      .catch((e) => {
        if (alive) setError(errorMessage(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [resource, page, search, status, reload, bridge]);
  const open = async (row: TradeRecord, edit = false) => {
    setOpening(String(row.id));
    setError("");
    try {
      const result = await bridge.request<Detail>(
        "/trade/" + resource + "/" + encodeURIComponent(String(row.id)),
      );
      if (active.current) {
        if (edit) setForm({ editing: result.record });
        else setDetail(result);
      }
    } catch (e) {
      if (active.current) setError(errorMessage(e));
    } finally {
      if (active.current) setOpening("");
    }
  };
  const act = async (row: TradeRecord, action: string) => {
    if (action === "edit") {
      void open(row, true);
      return;
    }
    if (actionBusy.current) return;
    actionBusy.current = true;
    setBusy(true);
    setError("");
    const identity = String(row.id) + ":" + action + ":" + row.version;
    let key = actionKeys.current.get(identity);
    if (!key) {
      key = keyFor(resource + "-" + action);
      actionKeys.current.set(identity, key);
    }
    try {
      const result = await bridge.request<Detail>(
        "/trade/" +
          resource +
          "/" +
          encodeURIComponent(String(row.id)) +
          "/actions/" +
          action,
        {
          method: "POST",
          body: JSON.stringify({ version: row.version, requestKey: key }),
        },
      );
      if (active.current) {
        if (detail?.record.id === row.id) setDetail(result);
        setReload((v) => v + 1);
        bridge.toast(actionLabels[action] + " completed");
      }
    } catch (e) {
      if (active.current) {
        setError(errorMessage(e));
        setReload((v) => v + 1);
      }
    } finally {
      actionBusy.current = false;
      if (active.current) setBusy(false);
    }
  };
  const printLink = (row: TradeRecord) =>
    "/api/trade/" +
    resource +
    "/" +
    encodeURIComponent(String(row.id)) +
    "/print";
  const buttons = (row: TradeRecord) => (
    <>
      {row.actions?.map((action) => (
        <button
          key={action}
          type="button"
          className="btn-sm"
          disabled={busy || !!opening}
          onClick={() => void act(row, action)}
        >
          {actionLabels[action] || "Edit"}
        </button>
      ))}
      {nextSteps(resource, row)
        .filter((step) => bridge.can(configs[step.resource].module, "create"))
        .map((step) => (
          <a
            key={step.resource}
            className="btn-sm trade-link"
            href={route(step.resource, step.sourceId)}
          >
            {step.label}
          </a>
        ))}
    </>
  );
  return (
    <>
      <div
        className="section-card"
        data-screen={"trade-" + resource + "-react"}
      >
        <div className="section-head">
          <div>
            <div className="section-title">{config.label}</div>
            <p className="hint">
              Pakistan · PKR · Saved per document with server-managed workflow
              actions
            </p>
          </div>
          {resource !== "comparisons" &&
            bridge.can(config.module, "create") && (
              <button
                type="button"
                className="btn-primary"
                onClick={() => setForm({})}
              >
                New {config.singular}
              </button>
            )}
        </div>
        <form
          className="filters"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            const fields = new FormData(event.currentTarget);
            setSearch(str(fields.get("search")).trim());
            setStatus(str(fields.get("status")).trim());
            setPage(1);
            setReload((v) => v + 1);
          }}
        >
          <input
            name="search"
            aria-label={"Search " + config.label.toLowerCase()}
            placeholder="Search number, partner or reference"
            maxLength={160}
          />
          <input
            name="status"
            aria-label="Status filter"
            placeholder="Status (optional)"
            maxLength={80}
          />
          <button type="submit" className="btn-secondary">
            Search
          </button>
        </form>
        {error && (
          <p className="modern-error" role="alert">
            {error}{" "}
            <button type="button" onClick={() => setReload((v) => v + 1)}>
              Reload Records
            </button>
          </p>
        )}
        <div className="table-wrap" aria-busy={loading}>
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th>
                  {config.area === "sales"
                    ? "Customer"
                    : "Supplier / Department"}
                </th>
                <th>Date</th>
                <th>Amount (PKR)</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6}>Loading documents…</td>
                </tr>
              ) : data.items.length ? (
                data.items.map((row) => (
                  <tr key={row.id} data-document-id={row.id}>
                    <td>
                      <button
                        type="button"
                        className="link-btn"
                        onClick={() => void open(row)}
                        disabled={!!opening}
                      >
                        {str(row[config.number]) || String(row.id)}
                      </button>
                    </td>
                    <td>
                      {str(
                        row.customerName ||
                          row.vendorName ||
                          row.department ||
                          row.requester,
                      )}
                    </td>
                    <td>{str(row[config.date]).slice(0, 10)}</td>
                    <td>
                      {money(row.amount ?? row.total ?? row.estimatedTotal)}
                    </td>
                    <td>
                      <span className="trade-status">{row.status}</span>
                    </td>
                    <td>
                      <div className="trade-actions">
                        <button
                          type="button"
                          className="btn-sm"
                          disabled={!!opening}
                          onClick={() => void open(row)}
                        >
                          Details
                        </button>
                        {bridge.can(config.module, "export") && (
                          <a
                            className="btn-sm trade-link"
                            href={printLink(row)}
                            target="_blank"
                            rel="noopener"
                          >
                            Print / PDF
                          </a>
                        )}
                        {buttons(row)}
                      </div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="empty">
                    No {config.label.toLowerCase()} found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="modern-pagination">
          <span>
            {data.total} documents · Page {page} of{" "}
            {Math.max(1, Math.ceil(data.total / data.pageSize))}
          </span>
          <div>
            <button
              type="button"
              className="btn-secondary"
              disabled={loading || page <= 1}
              onClick={() => setPage((v) => v - 1)}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={loading || page * data.pageSize >= data.total}
              onClick={() => setPage((v) => v + 1)}
            >
              Next
            </button>
          </div>
        </div>
      </div>
      {resource === "comparisons" && (
        <Comparison bridge={bridge} onChanged={() => setReload((v) => v + 1)} />
      )}
      {form && (
        <TradeForm
          resource={resource}
          bridge={bridge}
          user={user}
          editing={form.editing}
          sourceId={form.sourceId}
          leadId={form.leadId}
          onClose={() => setForm(null)}
          onSaved={(result) => {
            setForm(null);
            setPage(1);
            setReload((v) => v + 1);
            setDetail(result);
            bridge.toast(config.singular + " saved");
          }}
        />
      )}
      {detail && !form && (
        <Dialog
          title={config.singular + " " + str(detail.record[config.number])}
          busy={busy}
          onClose={() => setDetail(null)}
        >
          <div className="modal-body">
            <div className="detail-grid">
              {[
                [config.number, "Document"],
                ["status", "Status"],
                ["customerName", "Customer"],
                ["vendorName", "Vendor"],
                ["department", "Department"],
                [config.date, "Date"],
                ["dueDate", "Due Date"],
                ["referenceNo", "Reference"],
                ["paymentTerms", "Payment Terms"],
                ["deliveryStatus", "Delivery"],
                ["invoiceStatus", "Invoicing"],
                ["paymentStatus", "Payment"],
                ["matchStatus", "Three-way Match"],
              ]
                .filter(([field]) => detail.record[field] !== undefined)
                .map(([field, label]) => (
                  <div key={field}>
                    <span>{label}</span>
                    <b>{str(detail.record[field])}</b>
                  </div>
                ))}
            </div>
            <DocumentLines lines={economicLines(detail.record)} />
            {detail.context.sourceLines && (
              <>
                <h4>
                  Complete source quotation / order —{" "}
                  {detail.context.sourceNumber}
                </h4>
                <DocumentLines lines={detail.context.sourceLines} />
              </>
            )}
            <p className="trade-total">
              Total:{" "}
              {money(
                detail.record.amount ??
                  detail.record.total ??
                  detail.record.estimatedTotal,
              )}
            </p>
            {detail.record.balance !== undefined && (
              <p>
                Paid: {money(detail.record.paidAmount)} · Outstanding:{" "}
                <b>{money(detail.record.balance)}</b>
              </p>
            )}
            {detail.record.matchReason !== undefined && (
              <p className="detail-note">{str(detail.record.matchReason)}</p>
            )}
            {detail.record.notes !== undefined && (
              <p className="trade-notes">{str(detail.record.notes)}</p>
            )}
            {detail.record.terms !== undefined && (
              <p className="trade-notes">{str(detail.record.terms)}</p>
            )}
            {typeof detail.record.attachmentPath === "string" && (
              <a
                className="btn-secondary"
                href={
                  "/api/attachments/" +
                  encodeURIComponent(detail.record.attachmentPath)
                }
                target="_blank"
                rel="noopener"
              >
                Download Attachment
              </a>
            )}
            {error && (
              <p role="alert" className="modern-error">
                {error} Close and reopen details to refresh.
              </p>
            )}
          </div>
          <div className="modal-foot">
            <button
              type="button"
              className="btn-secondary"
              disabled={busy}
              onClick={() => setDetail(null)}
            >
              Close
            </button>
            {bridge.can(config.module, "export") && (
              <a
                className="btn-secondary"
                href={printLink(detail.record)}
                target="_blank"
                rel="noopener"
              >
                Print / PDF
              </a>
            )}
            {buttons(detail.record)}
          </div>
        </Dialog>
      )}
    </>
  );
}
function DocumentLines({
  lines,
}: {
  lines: NonNullable<TradeRecord["items"]>;
}) {
  return lines.length ? (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th>Qty</th>
            <th>Unit</th>
            <th>Rate</th>
            <th>Tax %</th>
            <th>Discount %</th>
            <th>Accepted / Rejected</th>
            <th>Total (PKR)</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, index) => (
            <tr key={index}>
              <td>
                {line.productName}
                <small>{line.description}</small>
              </td>
              <td>
                {str(line.quantity ?? line.deliveredQty ?? line.receivedQty)}
              </td>
              <td>{line.unit}</td>
              <td>
                {line.rate !== undefined || line.quotedRate !== undefined
                  ? money(line.rate ?? line.quotedRate)
                  : ""}
              </td>
              <td>{str(line.taxPercent)}</td>
              <td>{str(line.discountPercent)}</td>
              <td>
                {line.acceptedQty !== undefined
                  ? str(line.acceptedQty) + " / " + str(line.rejectedQty)
                  : ""}
              </td>
              <td>{line.total !== undefined ? money(line.total) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : null;
}
function Comparison({
  bridge,
  onChanged,
}: {
  bridge: Bridge;
  onChanged: () => void;
}) {
  const [source, setSource] = useState<TradeRecord | null>(null),
    [quotes, setQuotes] = useState<TradeRecord[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    if (!source) {
      setQuotes([]);
      return;
    }
    bridge
      .request<TradePageData>(
        "/trade/quotations?" +
          new URLSearchParams({ rfqId: String(source.id), pageSize: "100" }),
      )
      .then((result) => {
        if (active) {
          setQuotes(result.items);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [source, bridge]);
  return (
    <section className="section-card trade-comparison">
      <div className="section-head">
        <h3>Compare Vendor Offers</h3>
      </div>
      <Reference
        bridge={bridge}
        path="/trade/rfqs?status=Response%20Received%7CClosed%7CPO%20Created"
        label="RFQ for Comparison"
        name="compareRfq"
        value={source ? String(source.id) : ""}
        pinned={source ? [source] : []}
        onSelect={(items) =>
          setSource(items[0] ? (items[0] as TradeRecord) : null)
        }
      />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Quotation</th>
              <th>Supplier</th>
              <th>Total (PKR)</th>
              <th>Status</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {[...quotes]
              .sort((a, b) => Number(a.total || 0) - Number(b.total || 0))
              .map((quote) => (
                <tr key={quote.id}>
                  <td>{str(quote.quotationNo)}</td>
                  <td>{str(quote.vendorName)}</td>
                  <td>{money(quote.total)}</td>
                  <td>{quote.status}</td>
                  <td>
                    {quote.actions?.includes("award") && (
                      <button
                        type="button"
                        className="btn-sm"
                        disabled={busy}
                        onClick={() => {
                          setBusy(true);
                          void bridge
                            .request(
                              "/trade/quotations/" +
                                encodeURIComponent(String(quote.id)) +
                                "/actions/award",
                              {
                                method: "POST",
                                body: JSON.stringify({
                                  version: quote.version,
                                  requestKey: keyFor("comparison-award"),
                                }),
                              },
                            )
                            .then(() => {
                              setQuotes([]);
                              setSource(null);
                              onChanged();
                              bridge.toast("Quotation awarded");
                            })
                            .catch((e) => setError(errorMessage(e)))
                            .finally(() => setBusy(false));
                        }}
                      >
                        Award Quotation
                      </button>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {error && (
        <p role="alert" className="modern-error">
          {error}
        </p>
      )}
    </section>
  );
}
export function TradeDashboard({
  bridge,
  area,
}: {
  bridge: Bridge;
  area: "sales" | "purchase";
}) {
  const [data, setData] = useState<{
      registers: { key: Resource; count: number; total: number }[];
    } | null>(null),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    bridge
      .request<{
        registers: { key: Resource; count: number; total: number }[];
      }>("/trade/summary/" + area)
      .then((result) => {
        if (active) {
          setData(result);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [area, bridge, reload]);
  return (
    <section
      className="section-card"
      data-screen={"trade-" + area + "-dashboard-react"}
    >
      <div className="section-head">
        <div>
          <h3>{area === "sales" ? "Sales" : "Purchasing"} Dashboard</h3>
          <p className="hint">
            Current authorized document counts and values · PKR
          </p>
        </div>
      </div>
      {error && (
        <p className="modern-error" role="alert">
          {error}
          <button type="button" onClick={() => setReload((v) => v + 1)}>
            Try again
          </button>
        </p>
      )}
      {!data ? (
        <p aria-busy="true">Loading dashboard…</p>
      ) : (
        <div className="table-wrap" aria-busy="false">
          <table>
            <thead>
              <tr>
                <th>Register</th>
                <th>Documents</th>
                <th>Recorded Value (PKR)</th>
              </tr>
            </thead>
            <tbody>
              {data.registers.map((item) => (
                <tr key={item.key}>
                  <td>
                    <a href={route(item.key)}>{configs[item.key].label}</a>
                  </td>
                  <td>{item.count}</td>
                  <td>{money(item.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">
            Register values show all statuses. Use Accounting reports for posted
            balances and financial statements.
          </p>
        </div>
      )}
    </section>
  );
}
