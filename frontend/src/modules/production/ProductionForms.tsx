import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Bridge } from "../../types";
import { Dialog } from "../../components/Dialog";
import { Reference } from "../trade/Reference";
import { errorMessage } from "../../lib/api";
import { today, requestKey, money, str, type Row } from "../finance/types";
export interface ComponentRow {
  productId: string;
  product?: string;
  sku?: string;
  unit?: string;
  quantity: string;
  available?: string;
  shortage?: string;
  estimatedCost?: string;
}
export interface Bom extends Row {
  id: number;
  name: string;
  productId: string;
  product: string;
  quantity: string;
  conversionCost: string;
  version: string;
  components: ComponentRow[];
  actions: string[];
}
export interface Order extends Row {
  id: number;
  number: string;
  version: string;
  state: string;
  actions: string[];
  components: ComponentRow[];
  journalHref?: string | null;
  movementsHref?: string | null;
}
export type FormState = {
  kind: "bom" | "edit-bom" | "order";
  bom?: Bom;
  bomId?: string;
};
export function ProductionForm({
  form,
  bridge,
  onClose,
  onSaved,
}: {
  form: FormState;
  bridge: Bridge;
  onClose: () => void;
  onSaved: (row: Bom | Order) => void;
}) {
  const edit = form.kind === "edit-bom",
    isOrder = form.kind === "order";
  const [name, setName] = useState(form.bom?.name || ""),
    [productId, setProductId] = useState(form.bom?.productId || ""),
    [quantity, setQuantity] = useState(form.bom?.quantity || "1"),
    [cost, setCost] = useState(form.bom?.conversionCost || "0"),
    [date, setDate] = useState(today()),
    [lines, setLines] = useState<ComponentRow[]>(
      () =>
        form.bom?.components.map((l) => ({ ...l })) || [
          { productId: "", quantity: "1" },
        ],
    ),
    [bom, setBom] = useState<Bom | null>(null),
    [selectedId, setSelectedId] = useState(form.bomId || ""),
    [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const key = useRef(requestKey()),
    locked = useRef(false);
  useEffect(() => {
    if (!isOrder || !selectedId) return;
    let active = true;
    setLoading(true);
    setBom(null);
    bridge
      .request<{ record: Bom }>("/production/boms/" + selectedId)
      .then((r) => {
        if (active) {
          setBom(r.record);
          setQuantity(r.record.quantity);
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
  }, [bridge, selectedId, isOrder]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      const values = isOrder
        ? { bomId: bom?.id, bomVersion: bom?.version, quantity, date }
        : {
            name,
            quantity,
            conversionCost: cost,
            components: lines.map((l) => ({
              productId: l.productId,
              quantity: l.quantity,
            })),
            ...(edit
              ? { id: form.bom!.id, version: form.bom!.version }
              : { productId }),
          };
      const r = await bridge.request<{ record: Bom | Order }>(
        "/production/commands/" + form.kind,
        {
          method: "POST",
          body: JSON.stringify({ ...values, requestKey: key.current }),
        },
      );
      bridge.toast(
        isOrder ? "Manufacturing order created" : "Bill of materials saved",
      );
      onSaved(r.record);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={
        isOrder
          ? "New Manufacturing Order"
          : edit
            ? "Edit Bill of Materials"
            : "New Bill of Materials"
      }
      busy={busy}
      onClose={onClose}
    >
      <form className="trade-form" onSubmit={(e) => void submit(e)}>
        <div className="form-grid">
          {isOrder ? (
            <>
              <Reference
                bridge={bridge}
                path="/production/boms"
                name="bomId"
                label="Bill of materials"
                value={selectedId}
                required
                disabled={busy}
                onSelect={(rows) => {
                  setBom(null);
                  setLoading(!!rows[0]?.id);
                  setSelectedId(String(rows[0]?.id || ""));
                  setError("");
                }}
              />
              <label>
                Production date
                <input
                  name="date"
                  type="date"
                  value={date}
                  required
                  disabled={busy}
                  onChange={(e) => setDate(e.target.value)}
                />
              </label>
            </>
          ) : (
            <>
              <label>
                BoM name
                <input
                  name="name"
                  maxLength={160}
                  required
                  disabled={busy}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              {edit ? (
                <p>
                  Finished product: {form.bom?.product} ·{" "}
                  {form.bom?.sku as string}
                </p>
              ) : (
                <Reference
                  bridge={bridge}
                  path="/production/products"
                  name="productId"
                  label="Finished product"
                  value={productId}
                  required
                  disabled={busy}
                  onSelect={(rows) => setProductId(String(rows[0]?.id || ""))}
                />
              )}
              <label>
                Conversion cost per batch (PKR)
                <input
                  name="conversionCost"
                  type="number"
                  min="0"
                  step="0.01"
                  required
                  disabled={busy}
                  value={cost}
                  onChange={(e) => setCost(e.target.value)}
                />
              </label>
            </>
          )}
          <label>
            {isOrder ? "Finished quantity" : "Batch output quantity"}
            <input
              name="quantity"
              type="number"
              min="0.0001"
              step="0.0001"
              required
              disabled={busy || (isOrder && (!bom || loading))}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </label>
        </div>
        {isOrder ? (
          <>
            {loading && <p role="status">Loading bill of materials…</p>}
            {bom && (
              <>
                <p>
                  Product: {bom.product} · BoM: {bom.name}
                </p>
                <p>
                  Planned conversion cost: PKR{" "}
                  {money(
                    (Number(bom.conversionCost) * Number(quantity || 0)) /
                      Number(bom.quantity),
                  )}
                </p>
                <DataPreview
                  components={bom.components}
                  factor={Number(quantity || 0) / Number(bom.quantity)}
                />
                <p>
                  The order copies component quantities and conversion cost.
                  Later BoM edits do not change this order.
                </p>
              </>
            )}
          </>
        ) : (
          <>
            <p>
              Each component quantity is per batch. Use stock goods different
              from the finished product.
            </p>
            {lines.map((l, i) => (
              <fieldset className="finance-line" key={i}>
                <legend>Component {i + 1}</legend>
                <div className="form-grid">
                  <Reference
                    bridge={bridge}
                    path="/production/products"
                    name={"component-" + i}
                    label={"Component product " + (i + 1)}
                    value={l.productId}
                    required
                    disabled={busy}
                    pinned={
                      l.productId
                        ? [{ id: l.productId, name: l.product || l.productId }]
                        : []
                    }
                    onSelect={(rows) =>
                      setLines((items) =>
                        items.map((x, n) =>
                          n === i
                            ? {
                                ...x,
                                productId: String(rows[0]?.id || ""),
                                product: String(rows[0]?.name || ""),
                              }
                            : x,
                        ),
                      )
                    }
                  />
                  <label>
                    Component quantity {i + 1}
                    <input
                      aria-label={"Component quantity " + (i + 1)}
                      type="number"
                      step="0.0001"
                      min="0.0001"
                      required
                      value={l.quantity}
                      disabled={busy}
                      onChange={(e) =>
                        setLines((items) =>
                          items.map((x, n) =>
                            n === i ? { ...x, quantity: e.target.value } : x,
                          ),
                        )
                      }
                    />
                  </label>
                </div>
                {lines.length > 1 && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      setLines((items) => items.filter((_, n) => n !== i))
                    }
                  >
                    Remove component {i + 1}
                  </button>
                )}
              </fieldset>
            ))}
            <button
              type="button"
              disabled={busy || lines.length >= 100}
              onClick={() =>
                setLines((items) => [
                  ...items,
                  { productId: "", quantity: "1" },
                ])
              }
            >
              Add Component
            </button>
            {edit && (
              <p>
                This edits the BoM for future orders. Existing manufacturing
                orders retain their original component/cost snapshots.
              </p>
            )}
          </>
        )}
        {error && (
          <p role="alert" className="modern-error">
            {error}
          </p>
        )}
        <div className="modal-foot">
          <button type="button" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            disabled={busy || (isOrder && (!bom || loading))}
          >
            {busy ? "Saving…" : isOrder ? "Create Order" : "Save BoM"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function DataPreview({
  components,
  factor,
}: {
  components: ComponentRow[];
  factor: number;
}) {
  return (
    <div className="finance-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Component</th>
            <th>Required quantity</th>
            <th>Unit</th>
          </tr>
        </thead>
        <tbody>
          {components.map((c, i) => (
            <tr key={i}>
              <td>{c.product}</td>
              <td>{(Number(c.quantity) * factor).toFixed(4)}</td>
              <td>{str(c.unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
