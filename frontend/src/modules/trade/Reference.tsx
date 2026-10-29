import { useEffect, useState } from "react";
import type { Bridge } from "../../types";
import { errorMessage } from "../../lib/api";
import { str, type TradeRecord } from "./types";
interface Option {
  id: string | number;
  name?: string;
  version?: string;
  [key: string]: unknown;
}
export function Reference({
  bridge,
  path,
  label,
  value,
  onSelect,
  required = false,
  multiple = false,
  disabled = false,
  pinned = [],
  name,
}: {
  bridge: Bridge;
  path: string;
  label: string;
  value: string | string[];
  onSelect: (values: Option[]) => void;
  required?: boolean;
  multiple?: boolean;
  disabled?: boolean;
  pinned?: Option[];
  name: string;
}) {
  const [items, setItems] = useState<Option[]>([]),
    [search, setSearch] = useState(""),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(() => {
      bridge
        .request<{ items: Option[] }>(
          path +
            (path.includes("?") ? "&" : "?") +
            new URLSearchParams({ page: "1", pageSize: "100", search }),
        )
        .then((r) => {
          if (active) setItems(r.items);
        })
        .catch((e) => {
          if (active) setError(errorMessage(e));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 150);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [path, search, bridge, retry]);
  const selected = Array.isArray(value) ? value : [value];
  const unique = new Map<string, Option>();
  for (const item of [...pinned, ...items]) unique.set(String(item.id), item);
  const optionLabel = (item: Option) =>
    str(
      item.name ||
        item.quotationNo ||
        item.orderNo ||
        item.poNo ||
        item.invoiceNo ||
        item.rfqNo ||
        item.requestNo ||
        item.customerName ||
        item.id,
    ) + (item.status ? " · " + str(item.status) : "");
  return (
    <div className="modern-reference">
      <label>
        {label}
        <input
          type="search"
          aria-label={"Find " + label.toLowerCase()}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search records"
          maxLength={160}
          disabled={disabled}
        />
        <select
          name={name}
          aria-label={label}
          multiple={multiple}
          size={multiple ? 4 : undefined}
          required={required}
          disabled={disabled}
          value={multiple ? selected : selected[0] || ""}
          onChange={(e) =>
            onSelect(
              Array.from(e.target.selectedOptions)
                .filter((o) => o.value)
                .map((o) => unique.get(o.value) || { id: o.value }),
            )
          }
        >
          {!multiple && <option value="">Select…</option>}
          {selected
            .filter((id) => id && !unique.has(id))
            .map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          {[...unique.values()].map((item) => (
            <option key={String(item.id)} value={String(item.id)}>
              {optionLabel(item)}
            </option>
          ))}
        </select>
      </label>
      {loading && <small role="status">Loading choices…</small>}
      {multiple && (
        <small>
          Hold Ctrl to select several vendors. Search keeps selected vendors.
        </small>
      )}
      {error && (
        <span className="modern-error" role="alert">
          {error}{" "}
          <button type="button" onClick={() => setRetry((v) => v + 1)}>
            Try again
          </button>
        </span>
      )}
    </div>
  );
}
