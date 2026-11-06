import { useRef, useState, type FormEvent } from "react";
import { Dialog } from "../../components/Dialog";
import type { Bridge } from "../../types";
import { errorMessage } from "../../lib/api";
import { requestKey } from "../finance/types";
import type { Order } from "./ProductionForms";

export function ProductionCompletion({
  order,
  bridge,
  onClose,
  onSaved,
}: {
  order: Order;
  bridge: Bridge;
  onClose: () => void;
  onSaved: (order: Order) => void;
}) {
  const [quantity, setQuantity] = useState(String(order.quantity)),
    [cost, setCost] = useState(String(order.conversionCost)),
    [lines, setLines] = useState(
      order.components.map((c) => ({
        productId: c.productId,
        quantity: c.quantity,
        scrap: "0",
      })),
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const keys = useRef(new Map<string, string>()),
    locked = useRef(false);
  function scale(value: string) {
    setQuantity(value);
    const factor = Number(value) / Number(order.quantity);
    if (Number.isFinite(factor) && factor > 0 && factor <= 1) {
      setLines(
        order.components.map((c) => ({
          productId: c.productId,
          quantity: (Number(c.quantity) * factor).toFixed(4),
          scrap: "0",
        })),
      );
      setCost((Number(order.conversionCost) * factor).toFixed(2));
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    const payload = {
      id: order.id,
      version: order.version,
      producedQuantity: quantity,
      conversionCost: cost,
      components: lines,
    };
    const signature = JSON.stringify(payload);
    if (!keys.current.has(signature)) keys.current.set(signature, requestKey());
    try {
      const response = await bridge.request<{ record: Order }>(
        "/production/commands/complete",
        {
          method: "POST",
          body: JSON.stringify({
            ...payload,
            requestKey: keys.current.get(signature),
          }),
        },
      );
      onSaved(response.record);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={"Record Production · " + order.number}
      busy={busy}
      onClose={onClose}
    >
      <form onSubmit={submit}>
        <div className="modal-body credit-form">
          <p>
            Record the finished quantity and actual materials used. A partial
            completion creates a linked manufacturing backorder. Consumption
            excludes the separately entered scrap.
          </p>
          {error && (
            <p className="modern-error" role="alert">
              {error}
            </p>
          )}
          <div className="form-grid">
            <label>
              Finished quantity
              <input
                required
                type="number"
                min="0.0001"
                step="0.0001"
                max={String(order.quantity)}
                value={quantity}
                onChange={(e) => scale(e.target.value)}
              />
            </label>
            <label>
              Actual conversion cost (PKR)
              <input
                required
                type="number"
                min="0"
                step="0.01"
                value={cost}
                onChange={(e) => setCost(e.target.value)}
              />
            </label>
          </div>
          {order.components.map((component, index) => (
            <fieldset key={component.productId}>
              <legend>
                {component.product} · {component.unit}
              </legend>
              <div className="form-grid">
                <label>
                  Consumed quantity
                  <input
                    required
                    type="number"
                    min="0"
                    step="0.0001"
                    value={lines[index].quantity}
                    onChange={(e) =>
                      setLines((current) =>
                        current.map((line, i) =>
                          i === index
                            ? { ...line, quantity: e.target.value }
                            : line,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  Scrap quantity
                  <input
                    required
                    type="number"
                    min="0"
                    step="0.0001"
                    value={lines[index].scrap}
                    onChange={(e) =>
                      setLines((current) =>
                        current.map((line, i) =>
                          i === index
                            ? { ...line, scrap: e.target.value }
                            : line,
                        ),
                      )
                    }
                  />
                </label>
              </div>
            </fieldset>
          ))}
          <p>
            Consumed materials and conversion cost enter finished-goods value.
            Scrap posts separately to inventory loss. This action posts stock
            and accounting together.
          </p>
        </div>
        <div className="modal-foot">
          <button
            type="button"
            className="btn-secondary"
            disabled={busy}
            onClick={onClose}
          >
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={busy}>
            Post Production
          </button>
        </div>
      </form>
    </Dialog>
  );
}
