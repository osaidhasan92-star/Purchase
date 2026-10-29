import { useEffect, useRef, useState } from "react";
import type { Bridge } from "../../types";
import { Dialog } from "../../components/Dialog";
import { Pager, DataTable } from "../finance/FinanceReports";
import { money, str, requestKey, type PageData } from "../finance/types";
import { errorMessage } from "../../lib/api";
import {
  ProductionForm,
  type FormState,
  type Bom,
  type Order,
} from "./ProductionForms";
export type ProductionView = "manufacturing" | "boms" | "production-orders";
interface Summary {
  boms: number;
  states: Record<string, number>;
  completedCost: string;
}
export function ProductionPage({
  view,
  bridge,
}: {
  view: ProductionView;
  bridge: Bridge;
}) {
  const [data, setData] = useState<PageData>({
      items: [],
      total: 0,
      page: 1,
      pageSize: 25,
    }),
    [summary, setSummary] = useState<Summary | null>(null),
    [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [state, setState] = useState(""),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [reload, setReload] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [form, setForm] = useState<FormState | null>(null),
    [bom, setBom] = useState<Bom | null>(null),
    [order, setOrder] = useState<Order | null>(null);
  const locked = useRef(false),
    keys = useRef(new Map<string, string>());
  useEffect(() => {
    const bomId = new URLSearchParams(location.search).get("bomId");
    if (
      view === "production-orders" &&
      bomId &&
      bridge.can("manufacturing", "create")
    )
      setForm({ kind: "order", bomId });
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(
      () =>
        Promise.all([
          bridge.request<Summary>("/production/summary"),
          view === "manufacturing"
            ? Promise.resolve(null)
            : bridge.request<PageData>(
                "/production/" +
                  (view === "boms" ? "boms" : "orders") +
                  "?" +
                  new URLSearchParams({
                    page: String(page),
                    pageSize: "25",
                    search,
                    state,
                    from: start,
                    to: end,
                  }),
              ),
        ])
          .then(([s, r]) => {
            if (active) {
              setSummary(s);
              if (r) setData(r);
            }
          })
          .catch((e) => {
            if (active) setError(errorMessage(e));
          })
          .finally(() => {
            if (active) setLoading(false);
          }),
      150,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [bridge, view, page, search, state, start, end, reload]);
  async function open(id: number) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      if (view === "boms")
        setBom(
          (await bridge.request<{ record: Bom }>("/production/boms/" + id))
            .record,
        );
      else
        setOrder(
          (await bridge.request<{ record: Order }>("/production/orders/" + id))
            .record,
        );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  async function act(action: string) {
    if (!order || locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    const slot = order.id + ":" + order.version + ":" + action;
    if (!keys.current.has(slot)) keys.current.set(slot, requestKey());
    try {
      setOrder(
        (
          await bridge.request<{ record: Order }>(
            "/production/commands/" + action,
            {
              method: "POST",
              body: JSON.stringify({
                id: order.id,
                version: order.version,
                requestKey: keys.current.get(slot),
              }),
            },
          )
        ).record,
      );
      setReload((v) => v + 1);
      bridge.toast("Manufacturing order updated");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  const labels: Record<string, string> = {
    confirm: "Confirm Order",
    start: "Start Production",
    complete: "Complete Production",
    cancel: "Cancel Order",
  };
  const canCreate = bridge.can("manufacturing", "create");
  const newOrder = () => {
    setError("");
    setForm({ kind: "order" });
  };
  return (
    <section data-native-production={view} aria-busy={loading}>
      <div className="section-head">
        <div>
          <h2>
            {view === "manufacturing"
              ? "Production overview"
              : view === "boms"
                ? "Bill of materials register"
                : "Manufacturing order register"}
          </h2>
          <p>
            WH / Stock · PKR · One-step production and automatic
            stock/accounting
          </p>
        </div>
        {canCreate && (
          <div className="finance-actions">
            {view === "boms" ? (
              <button
                className="btn-primary"
                onClick={() => setForm({ kind: "bom" })}
              >
                New BoM
              </button>
            ) : (
              <button
                className="btn-primary"
                disabled={!summary?.boms}
                onClick={newOrder}
              >
                New Manufacturing Order
              </button>
            )}
          </div>
        )}
      </div>
      {canCreate && summary?.boms === 0 && view !== "boms" && (
        <p>
          Create a <a href="erp.html?view=boms">bill of materials</a> before
          creating a manufacturing order.
        </p>
      )}
      {error && (
        <p className="modern-error" role="alert">
          {error}{" "}
          <button onClick={() => setReload((v) => v + 1)}>Try again</button>
        </p>
      )}
      {loading ? (
        <p role="status">Loading manufacturing…</p>
      ) : view === "manufacturing" && summary ? (
        <>
          <div className="stats">
            {[
              ["Bills of materials", summary.boms],
              [
                "Open orders",
                (summary.states.Draft || 0) +
                  (summary.states.Confirmed || 0) +
                  (summary.states["In Progress"] || 0),
              ],
              ["Completed orders", summary.states.Done || 0],
              ["Completed output cost", "PKR " + money(summary.completedCost)],
            ].map(([t, v]) => (
              <div key={t} className="stat-card finance-stat">
                <span>{t}</span>
                <strong>{v}</strong>
              </div>
            ))}
          </div>
          <div className="erp-grid">
            <a className="erp-module" href="erp.html?view=boms">
              <h3>Bills of Materials</h3>
              <p>
                Define output batches, component requirements and conversion
                costs.
              </p>
            </a>
            <a className="erp-module" href="erp.html?view=production-orders">
              <h3>Manufacturing Orders</h3>
              <p>
                Confirm, start and complete production; inspect material
                shortages and posted costs.
              </p>
            </a>
          </div>
        </>
      ) : (
        <>
          <div className="finance-filters">
            <label>
              Search
              <input
                type="search"
                value={search}
                maxLength={160}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </label>
            {view === "production-orders" && (
              <>
                <label>
                  State
                  <select
                    aria-label="State"
                    value={state}
                    onChange={(e) => {
                      setState(e.target.value);
                      setPage(1);
                    }}
                  >
                    <option value="">All states</option>
                    {[
                      "Draft",
                      "Confirmed",
                      "In Progress",
                      "Done",
                      "Cancelled",
                    ].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <label>
                  From
                  <input
                    type="date"
                    value={start}
                    onChange={(e) => {
                      setStart(e.target.value);
                      setPage(1);
                    }}
                  />
                </label>
                <label>
                  To
                  <input
                    type="date"
                    value={end}
                    onChange={(e) => {
                      setEnd(e.target.value);
                      setPage(1);
                    }}
                  />
                </label>
              </>
            )}
          </div>
          <div className="finance-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {(view === "boms"
                    ? [
                        "BoM",
                        "Finished product",
                        "Output quantity",
                        "Components",
                        "Conversion cost PKR",
                        "Actions",
                      ]
                    : [
                        "Order",
                        "Product",
                        "Quantity",
                        "Date",
                        "State",
                        "Actual cost PKR",
                        "Actions",
                      ]
                  ).map((t) => (
                    <th key={t}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={str(r.id)}>
                    {view === "boms" ? (
                      <>
                        <td>{str(r.name)}</td>
                        <td>{str(r.product)}</td>
                        <td>{str(r.quantity)}</td>
                        <td>{str(r.components || 0)}</td>
                        <td>{money(r.conversionCost)}</td>
                      </>
                    ) : (
                      <>
                        <td>{str(r.number)}</td>
                        <td>{str(r.product)}</td>
                        <td>{str(r.quantity)}</td>
                        <td>{str(r.date)}</td>
                        <td>{str(r.state)}</td>
                        <td>{money(r.actualCost)}</td>
                      </>
                    )}
                    <td>
                      <button
                        className="btn-secondary btn-sm"
                        disabled={busy}
                        onClick={() => void open(Number(r.id))}
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
                {!data.items.length && (
                  <tr>
                    <td colSpan={7}>
                      No{" "}
                      {view === "boms"
                        ? "bills of materials"
                        : "manufacturing orders"}{" "}
                      found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            page={page}
            total={data.total}
            loading={loading}
            onPage={setPage}
          />
        </>
      )}
      {form && (
        <ProductionForm
          bridge={bridge}
          form={form}
          onClose={() => setForm(null)}
          onSaved={(r) => {
            const kind = form.kind;
            setForm(null);
            setReload((v) => v + 1);
            if (kind === "order") setOrder(r as Order);
            else setBom(r as Bom);
          }}
        />
      )}
      {bom && !form && (
        <Dialog
          title={"BoM " + bom.name}
          busy={busy}
          onClose={() => setBom(null)}
        >
          <div className="modal-body">
            <p>
              {bom.product} · Output per batch: {bom.quantity} · Conversion
              cost: PKR {money(bom.conversionCost)}
            </p>
            <DataTable
              columns={[
                ["product", "Component"],
                ["sku", "SKU"],
                ["quantity", "Quantity per batch"],
                ["unit", "Unit"],
              ]}
              rows={bom.components.map((c, i) => ({ ...c, id: i }))}
            />
            <p>
              Existing orders keep their copied component quantities and
              conversion cost.
            </p>
          </div>
          <div className="modal-foot">
            {bom.actions.includes("edit") && (
              <button
                onClick={() => {
                  setForm({ kind: "edit-bom", bom });
                  setBom(null);
                }}
              >
                Edit BoM
              </button>
            )}
            {canCreate && (
              <a
                className="btn-primary"
                href={"erp.html?view=production-orders&bomId=" + bom.id}
              >
                Create Manufacturing Order
              </a>
            )}
            <button onClick={() => setBom(null)}>Close</button>
          </div>
        </Dialog>
      )}
      {order && !form && (
        <Dialog
          title={"Manufacturing Order " + order.number}
          busy={busy}
          onClose={() => setOrder(null)}
        >
          <div className="modal-body">
            <p>
              {str(order.product)} × {str(order.quantity)} · {str(order.date)} ·{" "}
              <strong>{order.state}</strong>
            </p>
            <p>
              BoM: {str(order.bomName)} · Planned conversion cost: PKR{" "}
              {money(order.conversionCost)}
            </p>
            {order.state === "Done" ? (
              <p>Posted actual cost: PKR {money(order.actualCost)}</p>
            ) : (
              <>
                <p>
                  Current cost estimate: PKR {money(order.estimatedCost)} (not a
                  posting).
                </p>
                <p>
                  {order.materialsAvailable
                    ? "Materials currently available."
                    : "Material shortage: review required and available quantities before completion."}{" "}
                  Confirmation does not reserve stock.
                </p>
              </>
            )}
            <DataTable
              columns={[
                ["product", "Component"],
                ["quantity", "Required"],
                ["available", "Current available"],
                ["shortage", "Current shortage"],
                ["unit", "Unit"],
              ]}
              rows={order.components.map((c, i) => ({ ...c, id: i }))}
            />
            {order.journalHref && (
              <p>
                <a className="btn-secondary" href={order.journalHref}>
                  Journal Entries
                </a>
              </p>
            )}
            {order.movementsHref && (
              <p>
                <a className="btn-secondary" href={order.movementsHref}>
                  Stock Movements
                </a>
              </p>
            )}
            {error && (
              <p role="alert" className="modern-error">
                {error}
              </p>
            )}
          </div>
          <div className="modal-foot">
            {order.actions.map((a) => (
              <button
                key={a}
                className={a === "complete" ? "btn-primary" : "btn-secondary"}
                disabled={busy}
                onClick={() => void act(a)}
              >
                {labels[a]}
              </button>
            ))}
            {bridge.can("manufacturing", "export") && (
              <a
                className="btn-secondary"
                href={"/api/production/orders/" + order.id + "/print"}
                target="_blank"
                rel="noopener"
              >
                Print / Save as PDF
              </a>
            )}
            <button disabled={busy} onClick={() => setOrder(null)}>
              Close
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
