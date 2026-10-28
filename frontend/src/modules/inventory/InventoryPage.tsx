import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Bridge } from "../../types";
import { Dialog } from "../../components/Dialog";
import { Reference } from "../trade/Reference";
import { Pager, DataTable } from "../finance/FinanceReports";
import {
  money,
  str,
  today,
  requestKey,
  type Row,
  type PageData,
} from "../finance/types";
import { errorMessage } from "../../lib/api";
type Product = Row & {
  name: string;
  version: string;
  quantity: string;
  value: string;
  averageCost: string;
  type: string;
};
type Movement = Row & {
  id: number;
  version: string;
  canReturn: boolean;
  sourceLink?: { href: string; label: string } | null;
  journalHref?: string | null;
};
type Summary = {
  stockProducts: number;
  inventoryValue: string;
  movements: number;
  warehouse: string;
};
type Form = { kind: "adjust" | "scrap" | "return"; original?: Movement };
export function InventoryPage({
  view,
  bridge,
}: {
  view: "inventory" | "stock-moves";
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
    [type, setType] = useState("stock"),
    [productId, setProductId] = useState(
      () => new URLSearchParams(location.search).get("productId") || "",
    ),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [reload, setReload] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [detail, setDetail] = useState<Movement | null>(null),
    [form, setForm] = useState<Form | null>(null),
    [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const moves = view === "stock-moves";
  const params = new URLSearchParams({
    page: String(page),
    pageSize: "25",
    search,
    ...(moves ? { productId, from: start, to: end } : { type }),
  });
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(
      () =>
        Promise.all([
          bridge.request<PageData>(
            "/inventory/" + (moves ? "movements" : "products") + "?" + params,
          ),
          bridge.request<Summary>("/inventory/summary"),
        ])
          .then(([list, s]) => {
            if (active) {
              setData(list);
              setSummary(s);
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
  }, [bridge, view, page, search, type, productId, start, end, reload]);
  async function open(id: number) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      setDetail(
        (
          await bridge.request<{ record: Movement }>(
            "/inventory/movements/" + id,
          )
        ).record,
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <section
      data-native-inventory={view}
      aria-busy={loading}
      className="inventory-workspace"
    >
      <div className="section-head">
        <div>
          <h2>{moves ? "Stock movement register" : "Stock balances"}</h2>
          <p>WH / Stock · PKR · Perpetual average-cost valuation</p>
        </div>
        {bridge.can("inventory", "approve") && (
          <div className="finance-actions">
            <button
              className="btn-primary"
              disabled={busy}
              onClick={() => setForm({ kind: "adjust" })}
            >
              Stock Adjustment
            </button>
            <button
              className="btn-secondary"
              disabled={busy}
              onClick={() => setForm({ kind: "scrap" })}
            >
              Scrap Stock
            </button>
          </div>
        )}
      </div>
      {summary && (
        <div className="stats">
          {[
            ["Stock products", String(summary.stockProducts)],
            ["Inventory value", "PKR " + money(summary.inventoryValue)],
            ["Stock movements", String(summary.movements)],
            ["Warehouse", summary.warehouse],
          ].map(([t, v]) => (
            <div key={t} className="stat-card finance-stat">
              <span>{t}</span>
              <strong>{v}</strong>
            </div>
          ))}
        </div>
      )}
      <div className="finance-filters">
        <label>
          Search
          <input
            type="search"
            maxLength={160}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </label>
        {moves ? (
          <>
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
            {productId && (
              <p>
                Product: {productId}{" "}
                <button
                  onClick={() => {
                    setProductId("");
                    setPage(1);
                  }}
                >
                  Clear product filter
                </button>
              </p>
            )}
            {bridge.can("inventory", "export") && (
              <a
                className="btn-secondary"
                href={"/api/inventory/movements/export?" + params}
              >
                Export current page CSV
              </a>
            )}
          </>
        ) : (
          <label>
            Product type
            <select
              aria-label="Product type"
              value={type}
              onChange={(e) => {
                setType(e.target.value);
                setPage(1);
              }}
            >
              <option value="stock">Stock goods</option>
              <option value="service">Services</option>
              <option value="">All products</option>
            </select>
          </label>
        )}
      </div>
      {error && (
        <p role="alert" className="modern-error">
          {error}{" "}
          <button onClick={() => setReload((v) => v + 1)}>Try again</button>
        </p>
      )}
      {loading ? (
        <p role="status">Loading inventory…</p>
      ) : (
        <div className="finance-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                {(moves
                  ? [
                      "Movement",
                      "Date",
                      "Product",
                      "Operation",
                      "Quantity",
                      "Value PKR",
                      "Actions",
                    ]
                  : [
                      "Product",
                      "SKU",
                      "Type",
                      "On hand",
                      "Average cost PKR",
                      "Value PKR",
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
                  {moves ? (
                    <>
                      <td>{str(r.number)}</td>
                      <td>{str(r.date)}</td>
                      <td>{str(r.product)}</td>
                      <td>{str(r.kind)}</td>
                      <td>
                        {str(r.quantity)} {str(r.unit)}
                      </td>
                      <td>{money(r.value)}</td>
                      <td>
                        <button
                          className="btn-secondary btn-sm"
                          disabled={busy}
                          onClick={() => void open(Number(r.id))}
                        >
                          View
                        </button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td>{str(r.name)}</td>
                      <td>{str(r.sku)}</td>
                      <td>{str(r.type)}</td>
                      <td>
                        {r.type === "stock"
                          ? str(r.quantity) + " " + str(r.unit)
                          : "—"}
                      </td>
                      <td>{r.type === "stock" ? money(r.averageCost) : "—"}</td>
                      <td>{r.type === "stock" ? money(r.value) : "—"}</td>
                      <td>
                        <a
                          className="btn-secondary btn-sm"
                          href={
                            "erp.html?view=stock-moves&productId=" +
                            encodeURIComponent(str(r.id))
                          }
                        >
                          Movements
                        </a>
                      </td>
                    </>
                  )}
                </tr>
              ))}
              {!data.items.length && (
                <tr>
                  <td colSpan={7}>
                    No {moves ? "stock movements" : "products"} found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <Pager
        page={page}
        total={data.total}
        loading={loading}
        onPage={setPage}
      />
      <p>
        Receipts increase stock; validated deliveries reduce stock and post cost
        of goods sold. Returns reverse stock quantities and valuation;
        commercial credits/refunds require separate accounting treatment.
      </p>
      {form && (
        <InventoryForm
          bridge={bridge}
          form={form}
          onClose={() => setForm(null)}
          onSaved={(r) => {
            setForm(null);
            setReload((v) => v + 1);
            setDetail(r);
          }}
        />
      )}
      {detail && !form && (
        <Dialog
          title={"Stock Movement " + str(detail.number)}
          busy={busy}
          onClose={() => setDetail(null)}
        >
          <div className="modal-body">
            <DataTable
              columns={[
                ["product", "Product"],
                ["date", "Date"],
                ["kind", "Operation"],
                ["quantity", "Quantity"],
                ["value", "Value PKR", true],
                ["returnRemaining", "Unreturned quantity"],
              ]}
              rows={[detail]}
            />
            <p>Source: {str(detail.source)}</p>
            {!!detail.reason && <p>Reason: {str(detail.reason)}</p>}
            {!!detail.returnOf && (
              <p>Return of movement ID {str(detail.returnOf)}</p>
            )}
            {detail.sourceLink && (
              <p>
                <a
                  className="btn-secondary"
                  href={detail.sourceLink.href}
                  target="_blank"
                  rel="noopener"
                >
                  {detail.sourceLink.label}
                </a>
              </p>
            )}
            {detail.journalHref && (
              <p>
                <a className="btn-secondary" href={detail.journalHref}>
                  Journal Entries
                </a>
              </p>
            )}
            <p>Posted stock movements are immutable.</p>
          </div>
          <div className="modal-foot">
            {detail.canReturn && (
              <button
                className="btn-primary"
                disabled={busy}
                onClick={() => {
                  setForm({ kind: "return", original: detail });
                  setDetail(null);
                }}
              >
                Return Stock
              </button>
            )}
            <button onClick={() => setDetail(null)}>Close</button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
function InventoryForm({
  bridge,
  form,
  onClose,
  onSaved,
}: {
  bridge: Bridge;
  form: Form;
  onClose: () => void;
  onSaved: (r: Movement) => void;
}) {
  const [selected, setSelected] = useState<Product | null>(null),
    [quantity, setQuantity] = useState(""),
    [cost, setCost] = useState("0"),
    [date, setDate] = useState(today()),
    [reason, setReason] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const key = useRef(requestKey()),
    locked = useRef(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      const payload = {
        requestKey: key.current,
        quantity,
        date,
        reason,
        ...(form.kind === "return"
          ? { moveId: form.original!.id, version: form.original!.version }
          : {
              productId: selected?.id,
              version: selected?.version,
              ...(form.kind === "adjust" ? { unitCost: cost } : {}),
            }),
      };
      const result = await bridge.request<{ record: Movement }>(
        "/inventory/commands/" + form.kind,
        { method: "POST", body: JSON.stringify(payload) },
      );
      bridge.toast("Stock movement posted");
      onSaved(result.record);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  const title =
    form.kind === "return"
      ? "Return Stock"
      : form.kind === "scrap"
        ? "Scrap Stock"
        : "Stock Adjustment";
  return (
    <Dialog title={title} busy={busy} onClose={onClose}>
      <form className="trade-form" onSubmit={(e) => void submit(e)}>
        {form.original ? (
          <p>
            {str(form.original.product)} · {str(form.original.kind)} · Return
            remaining: {str(form.original.returnRemaining)}{" "}
            {str(form.original.unit)}
          </p>
        ) : (
          <>
            <Reference
              bridge={bridge}
              path="/inventory/products?type=stock"
              name="productId"
              label="Stock product"
              value={str(selected?.id || "")}
              required
              disabled={busy}
              onSelect={(rows) =>
                setSelected((rows[0] as unknown as Product) || null)
              }
            />
            {selected && (
              <p>
                On hand: {selected.quantity} · Average cost: PKR{" "}
                {money(selected.averageCost)}
              </p>
            )}
          </>
        )}
        <div className="form-grid">
          <label>
            {form.kind === "adjust" ? "Signed quantity (+ / −)" : "Quantity"}
            <input
              name="quantity"
              type="number"
              step="0.0001"
              min={form.kind === "adjust" ? undefined : "0.0001"}
              value={quantity}
              required
              disabled={busy}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </label>
          {form.kind === "adjust" && (
            <label>
              Incoming unit cost (PKR)
              <input
                name="unitCost"
                type="number"
                min="0"
                step="0.0001"
                value={cost}
                required
                disabled={busy}
                onChange={(e) => setCost(e.target.value)}
              />
            </label>
          )}
          <label>
            Posting date
            <input
              name="date"
              type="date"
              value={date}
              required
              disabled={busy}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
          <label>
            Reason
            <input
              name="reason"
              maxLength={300}
              value={reason}
              required
              disabled={busy}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
        </div>
        <p>
          {form.kind === "adjust"
            ? "Positive quantity adds stock at the entered cost; negative quantity issues stock at current average cost."
            : form.kind === "scrap"
              ? "Scrap issues a positive entered quantity at current average cost."
              : "Customer returns recover original delivery cost; vendor returns issue stock at current average cost."}{" "}
          Posting updates stock and related accounting atomically.
        </p>
        {error && (
          <p role="alert" className="modern-error">
            {error}
          </p>
        )}
        <div className="modal-foot">
          <button type="button" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={busy}>
            {busy ? "Posting…" : "Post Movement"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
