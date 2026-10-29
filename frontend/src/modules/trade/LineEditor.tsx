import type { Bridge } from "../../types";
import { Reference } from "./Reference";
import { money, str, type Resource, type TradeLine } from "./types";
export function LineEditor({
  bridge,
  resource,
  lines,
  onChange,
  priced = true,
  locked = false,
}: {
  bridge: Bridge;
  resource: Resource;
  lines: TradeLine[];
  onChange: (lines: TradeLine[]) => void;
  priced?: boolean;
  locked?: boolean;
}) {
  const set = (index: number, key: string, value: unknown) => {
    const next = lines.map((line, i) =>
      i === index ? { ...line, [key]: value } : line,
    );
    if (key === "receivedQty" && Number(next[index].rejectedQty || 0) === 0)
      next[index].acceptedQty = Number(value);
    onChange(next);
  };
  const invoice = resource === "invoices" || resource === "customerInvoices",
    receiving = resource === "receipts",
    delivery = resource === "deliveries",
    vendorQuote = resource === "quotations";
  const fields = receiving
    ? [
        ["receivedQty", "Received"],
        ["acceptedQty", "Accepted"],
        ["rejectedQty", "Rejected"],
      ]
    : delivery
      ? [["deliveredQty", "Dispatch Now"]]
      : [
          ["quantity", invoice ? "Invoice Qty" : "Quantity"],
          ...(priced
            ? [
                ["rate", "Unit Rate (PKR)"],
                ["discountPercent", "Discount %"],
                ["taxPercent", "Tax %"],
              ]
            : []),
        ];
  return (
    <section className="trade-lines">
      <div className="section-head">
        <h4>
          {receiving
            ? "Receipt and inspection"
            : delivery
              ? "Delivery quantities"
              : invoice
                ? "Invoice quantities"
                : "Line items"}
        </h4>
        {!locked && !receiving && !delivery && !invoice && !vendorQuote && (
          <button
            type="button"
            className="btn-secondary"
            onClick={() =>
              onChange([
                ...lines,
                { quantity: 1, rate: 0, taxPercent: 0, discountPercent: 0 },
              ])
            }
          >
            Add Line
          </button>
        )}
      </div>
      {!lines.length && (
        <p className="hint">Select a source document to load its lines.</p>
      )}
      {lines.map((line, index) => (
        <div className="trade-line" key={index} data-line-index={index}>
          <div className="trade-line-title">
            {!locked && !invoice && !receiving && !delivery && !vendorQuote ? (
              <Reference
                bridge={bridge}
                path="/products"
                label={"Product " + (index + 1)}
                name={"product-" + index}
                value={str(line.productId)}
                pinned={
                  line.productId
                    ? [{ id: line.productId, name: line.productName }]
                    : []
                }
                required
                onSelect={(values) => {
                  const item = values[0];
                  if (item)
                    onChange(
                      lines.map((old, i) =>
                        i === index
                          ? {
                              ...old,
                              productId: item.id,
                              productName: str(item.name),
                              unit: str(item.unit) || "Each",
                              rate: Number(item.rate || 0),
                            }
                          : old,
                      ),
                    );
                  else set(index, "productId", "");
                }}
              />
            ) : (
              <>
                <b>{line.productName || "Product"}</b>
                <small>
                  {line.unit || "Each"}
                  {line.remaining !== undefined
                    ? " · Remaining: " + str(line.remaining)
                    : ""}
                  {invoice
                    ? " · Uninvoiced: " + str(line.invoiceRemaining)
                    : ""}
                  {resource === "invoices"
                    ? " · Accepted/unbilled: " + str(line.acceptedUnbilled)
                    : ""}
                </small>
              </>
            )}
            {!locked &&
              !receiving &&
              !delivery &&
              !invoice &&
              !vendorQuote &&
              lines.length > 1 && (
                <button
                  type="button"
                  className="btn-sm"
                  onClick={() => onChange(lines.filter((_, i) => i !== index))}
                >
                  Remove Line {index + 1}
                </button>
              )}
          </div>
          <div className="trade-line-fields">
            {fields.map(([name, label]) => (
              <label key={name}>
                {label}
                <input
                  aria-label={label + " " + (index + 1)}
                  name={name + "-" + index}
                  type="number"
                  min="0"
                  max={name.includes("Percent") ? 100 : 1e12}
                  step={name.includes("Percent") ? "0.0001" : "0.0001"}
                  required
                  value={Number(line[name] || 0)}
                  disabled={
                    locked ||
                    (vendorQuote && name === "quantity") ||
                    (invoice && name !== "quantity")
                  }
                  onChange={(e) => set(index, name, Number(e.target.value))}
                />
              </label>
            ))}
            {priced && !receiving && !delivery && (
              <div className="trade-line-total">
                <small>Estimated total</small>
                <b>
                  {money(
                    Number(line.quantity || 0) *
                      Number(line.rate ?? line.quotedRate ?? 0) *
                      (1 - Number(line.discountPercent || 0) / 100) *
                      (1 + Number(line.taxPercent || 0) / 100),
                  )}
                </b>
              </div>
            )}
          </div>
          {receiving ? (
            <div className="grid2">
              <label>
                Inspection
                <select
                  value={str(line.inspection) || "Accepted"}
                  onChange={(e) => set(index, "inspection", e.target.value)}
                >
                  <option>Accepted</option>
                  <option>Partial</option>
                  <option>Rejected</option>
                </select>
              </label>
              <label>
                Remark
                <input
                  maxLength={1000}
                  value={str(line.remark)}
                  onChange={(e) => set(index, "remark", e.target.value)}
                />
              </label>
            </div>
          ) : (
            !invoice &&
            !delivery && (
              <label>
                Description
                <input
                  maxLength={2000}
                  disabled={locked}
                  value={str(line.description)}
                  onChange={(e) => set(index, "description", e.target.value)}
                />
              </label>
            )
          )}
        </div>
      ))}
      {priced && lines.length > 0 && (
        <p className="hint">
          Prices and taxes are calculated again by the server when you save.
        </p>
      )}
    </section>
  );
}
