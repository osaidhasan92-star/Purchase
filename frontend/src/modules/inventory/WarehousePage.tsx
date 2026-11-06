import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Bridge } from "../../types";
import { Dialog } from "../../components/Dialog";
import { Reference } from "../trade/Reference";
import { errorMessage } from "../../lib/api";
import { today, requestKey } from "../finance/types";
type Row = {
  [key: string]: unknown;
  productId?: string;
  name?: string;
  version?: string;
  locations?: Record<string, string>;
  orderId?: string;
  orderNumber?: string;
  kind?: string;
};
export function WarehousePage({ bridge }: { bridge: Bridge }) {
  const initial =
    new URLSearchParams(location.search).get("area") || "locations";
  const area = [
    "locations",
    "reservations",
    "backorders",
    "transfers",
  ].includes(initial)
    ? initial
    : "locations";
  const inspectionProduct =
    new URLSearchParams(location.search).get("inspectProduct") || "";
  const canInspect =
    bridge.can("inventory", "create") && bridge.can("inventory", "approve");
  const [items, setItems] = useState<Row[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(1),
    [reload, setReload] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [form, setForm] = useState(!!inspectionProduct && canInspect),
    [product, setProduct] = useState(inspectionProduct),
    [stock, setStock] = useState<Row | null>(null),
    [source, setSource] = useState(inspectionProduct ? "Returns" : "Stock"),
    [target, setTarget] = useState(inspectionProduct ? "Stock" : "Production"),
    [quantity, setQuantity] = useState(""),
    [date, setDate] = useState(today()),
    [reason, setReason] = useState(""),
    [busy, setBusy] = useState(false);
  const lock = useRef(false),
    keys = useRef(new Map<string, string>());
  useEffect(() => {
    let active = true;
    setLoading(true);
    bridge
      .request<{ items: Row[]; total: number }>(
        "/warehouse/" + area + "?page=" + page + "&pageSize=25",
      )
      .then((r) => {
        if (active) {
          setItems(r.items);
          setTotal(r.total);
        }
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
  }, [area, page, reload, bridge]);
  useEffect(() => {
    let active = true;
    setStock(null);
    if (product)
      bridge
        .request<{ record: Row }>(
          "/inventory/products/" + encodeURIComponent(product),
        )
        .then((r) => {
          if (active) setStock(r.record);
        })
        .catch((e) => {
          if (active) setError(errorMessage(e));
        });
    return () => {
      active = false;
    };
  }, [product, reload, bridge]);
  const command = async (command: string, payload: Record<string, unknown>) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    const { version: _version, ...semanticPayload } = payload;
    const signature = JSON.stringify({ command, payload: semanticPayload });
    let key = keys.current.get(signature);
    if (!key) {
      key = requestKey();
      keys.current.set(signature, key);
    }
    try {
      await bridge.request("/warehouse/commands/" + command, {
        method: "POST",
        body: JSON.stringify({ ...payload, requestKey: key }),
      });
      keys.current.delete(signature);
      setForm(false);
      setReload((v) => v + 1);
      bridge.toast(
        command === "transfer"
          ? "Internal transfer validated"
          : "Availability checked",
      );
    } catch (e) {
      setError(errorMessage(e));
      setReload((v) => v + 1);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  const transfer = (event: FormEvent) => {
    event.preventDefault();
    void command("transfer", {
      productId: product,
      fromLocation: source,
      toLocation: target,
      quantity,
      date,
      reason,
      version: stock?.warehouseVersion,
    });
  };
  const labels: Record<string, string> = {
    locations: "Locations & Availability",
    reservations: "Reservations",
    backorders: "Backorders",
    transfers: "Internal Transfers",
  };
  const columns =
    area === "locations"
      ? [
          "Product",
          "Stock",
          "Production",
          "Returns",
          "Stock reserved",
          "Production reserved",
          "Stock available",
          "Inspection",
        ]
      : area === "reservations"
        ? ["Order", "Line", "Product", "Required", "Reserved", "Action"]
        : area === "backorders"
          ? ["Backorder", "Order", "Product", "Remaining", "Status", "Action"]
          : ["Transfer", "Date", "Product", "From", "To", "Quantity", "Reason"];
  return (
    <section
      className="section-card"
      data-native-warehouse
      data-native-inventory="warehouse"
      aria-busy={loading}
    >
      <div className="section-head">
        <div>
          <h2>Warehouse Operations</h2>
          <p className="hint">
            One warehouse · Stock, Production and Returns · Internal transfers
            preserve total quantity and value.
          </p>
        </div>
        {bridge.can("inventory", "create") &&
          bridge.can("inventory", "approve") && (
            <button
              className="btn-primary"
              onClick={() => {
                setProduct("");
                setQuantity("");
                setReason("");
                setError("");
                setForm(true);
              }}
            >
              New Internal Transfer
            </button>
          )}
      </div>
      <div className="warehouse-tabs">
        {Object.entries(labels).map(([value, label]) => (
          <a
            className="btn-sm"
            aria-current={area === value ? "page" : undefined}
            key={value}
            href={"erp.html?view=warehouse&area=" + value}
          >
            {label}
          </a>
        ))}
      </div>
      <p className="hint">
        Confirm Sales or Manufacturing orders to reserve materials.
        Manufacturing allocations are managed in Manufacturing Orders. When new
        stock arrives, use Check Availability. Returned goods must be
        transferred from Returns to Stock before dispatch.
      </p>
      {error && !form && (
        <p role="alert" className="modern-error">
          {error}
        </p>
      )}
      <div className="finance-table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((r, index) => (
              <tr key={String(r.id || r.productId || index)}>
                {area === "locations" ? (
                  <>
                    <td>{r.name}</td>
                    {["Stock", "Production", "Returns"].map((loc) => (
                      <td key={loc}>{r.locations?.[loc] || "0"}</td>
                    ))}
                    <td>{String(r.reserved)}</td>
                    <td>{String(r.productionReserved)}</td>
                    <td>{String(r.available)}</td>
                    <td>
                      {canInspect && Number(r.locations?.Returns) > 0 && (
                        <a
                          href={
                            "erp.html?view=warehouse&area=transfers&inspectProduct=" +
                            encodeURIComponent(String(r.productId))
                          }
                        >
                          Inspect / Restock
                        </a>
                      )}
                    </td>
                  </>
                ) : area === "reservations" ? (
                  <>
                    <td>{r.orderNumber}</td>
                    <td>{Number(r.lineIndex) + 1}</td>
                    <td>{String(r.product)}</td>
                    <td>{String(r.required)}</td>
                    <td>{String(r.quantity)}</td>
                    <td>
                      {bridge.can("inventory", "approve") && (
                        <button
                          className="btn-sm"
                          disabled={busy}
                          onClick={() =>
                            void command("reserve", { orderId: r.orderId })
                          }
                        >
                          Check Availability
                        </button>
                      )}
                      {bridge.can("inventory", "approve") &&
                        Number(r.quantity) > 0 && (
                          <button
                            className="btn-sm"
                            disabled={busy}
                            onClick={() =>
                              void command("release", { orderId: r.orderId })
                            }
                          >
                            Release Order Stock
                          </button>
                        )}
                    </td>
                  </>
                ) : area === "backorders" ? (
                  <>
                    <td>{String(r.number)}</td>
                    <td>
                      <a
                        href={
                          "erp.html?view=" +
                          (r.kind === "sales" ? "sales-orders" : "orders") +
                          "&search=" +
                          encodeURIComponent(r.orderNumber || "")
                        }
                      >
                        {r.orderNumber}
                      </a>
                      {r.originNumber ? (
                        <small className="warehouse-origin">
                          <a
                            href={
                              "erp.html?view=" +
                              (r.kind === "sales"
                                ? "sales-deliveries"
                                : "receipts") +
                              "&module=inventory&search=" +
                              encodeURIComponent(String(r.originNumber))
                            }
                          >
                            From {String(r.originNumber)}
                          </a>
                        </small>
                      ) : null}
                    </td>
                    <td>{String(r.product)}</td>
                    <td>{String(r.quantity)}</td>
                    <td>{String(r.status)}</td>
                    <td>
                      {((r.kind === "sales" &&
                        bridge.can("sales_deliveries", "create") &&
                        bridge.can("sales_orders")) ||
                        (r.kind === "purchase" &&
                          bridge.can("receipts", "create") &&
                          bridge.can("orders"))) && (
                        <a
                          className="btn-sm"
                          href={
                            "erp.html?view=" +
                            (r.kind === "sales"
                              ? "sales-deliveries"
                              : "receipts") +
                            "&module=inventory&sourceId=" +
                            encodeURIComponent(r.orderId || "")
                          }
                        >
                          Fulfill Backorder
                        </a>
                      )}{" "}
                      {r.kind === "sales" &&
                        bridge.can("inventory", "approve") && (
                          <button
                            className="btn-sm"
                            disabled={busy}
                            onClick={() =>
                              void command("reserve", { orderId: r.orderId })
                            }
                          >
                            Check Availability
                          </button>
                        )}
                    </td>
                  </>
                ) : (
                  <>
                    {[
                      "number",
                      "date",
                      "product",
                      "fromLocation",
                      "toLocation",
                      "quantity",
                      "reason",
                    ].map((c) => (
                      <td key={c}>{String(r[c] || "")}</td>
                    ))}
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !items.length && (
          <p className="empty">No records found.</p>
        )}
      </div>
      <div className="section-head">
        <button
          className="btn-sm"
          disabled={loading || page === 1}
          onClick={() => setPage((v) => v - 1)}
        >
          Previous
        </button>
        <span>
          Page {page} · {total} records
        </span>
        <button
          className="btn-sm"
          disabled={loading || page * 25 >= total}
          onClick={() => setPage((v) => v + 1)}
        >
          Next
        </button>
      </div>
      {form && (
        <Dialog
          title="Internal Transfer"
          busy={busy}
          onClose={() => setForm(false)}
        >
          <form className="modal-body credit-form" onSubmit={transfer}>
            {source === "Returns" && (
              <p>
                Inspect returned goods before releasing them. Transfer only
                approved usable quantities to Stock, and record your inspection
                decision in the reason. Unusable goods remain in Returns for
                separate disposition.
              </p>
            )}
            {error && (
              <p role="alert" className="modern-error">
                {error}
              </p>
            )}
            <Reference
              bridge={bridge}
              path="/inventory/products?type=stock"
              label="Stock Product"
              name="transferProduct"
              value={product}
              pinned={
                product && stock
                  ? [{ id: product, name: String(stock.name || product) }]
                  : []
              }
              onSelect={(values) => setProduct(String(values[0]?.id || ""))}
              required
            />
            <div className="grid2">
              <label>
                From Location
                <select
                  aria-label="From Location"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  {["Stock", "Production", "Returns"].map((loc) => (
                    <option key={loc}>{loc}</option>
                  ))}
                </select>
              </label>
              <label>
                To Location
                <select
                  aria-label="To Location"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                >
                  {["Stock", "Production", "Returns"].map((loc) => (
                    <option key={loc}>{loc}</option>
                  ))}
                </select>
              </label>
            </div>
            {stock && (
              <p className="hint">
                Locations:{" "}
                {Object.entries(stock.locations || {})
                  .map(([k, v]) => k + ": " + v)
                  .join(" · ")}{" "}
                · Available in Stock: {String(stock.available)}
              </p>
            )}
            <label>
              Quantity
              <input
                aria-label="Transfer Quantity"
                type="number"
                min="0.0001"
                step="0.0001"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                required
              />
            </label>
            <label>
              Date
              <input
                aria-label="Transfer Date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                required
              />
            </label>
            <label>
              Reason
              <textarea
                aria-label="Transfer Reason"
                value={reason}
                maxLength={300}
                onChange={(e) => setReason(e.target.value)}
                required
              />
            </label>
            <div className="form-actions">
              <button
                className="btn-sm"
                type="button"
                disabled={busy}
                onClick={() => setForm(false)}
              >
                Cancel
              </button>
              <button className="btn-primary" disabled={busy || !stock}>
                Validate Transfer
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </section>
  );
}
