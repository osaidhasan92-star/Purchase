import { useEffect, useRef, useState, type FormEvent } from "react";
import { flushSync } from "react-dom";
import type { Bridge } from "../types";
import { errorMessage } from "../lib/api";
export type MasterKind = "vendors" | "products" | "leads" | "reminders";
export interface MasterRecord {
  id: string | number;
  version: string;
  name?: string;
  [key: string]: string | number | boolean | undefined | null;
}
export interface MasterCommands {
  open: (id?: string | number) => void;
  save: () => Promise<void>;
}
interface Field {
  name: string;
  label: string;
  id: string;
  type?: string;
  options?: string[];
  max?: number;
  reference?: "customers" | "leads" | "assignees";
}
const stages = ["New", "Contacted", "Qualified", "Quotation Required"];
const fields: Record<MasterKind, Field[]> = {
  leads: [
    {
      name: "customerId",
      label: "Customer",
      id: "crm-lead-customer",
      reference: "customers",
    },
    { name: "contact", label: "Contact", id: "crm-lead-contact", max: 160 },
    {
      name: "email",
      label: "Email",
      id: "crm-lead-email",
      type: "email",
      max: 254,
    },
    {
      name: "stage",
      label: "Stage",
      id: "crm-lead-stage-input",
      options: stages,
    },
    {
      name: "value",
      label: "Opportunity Value (PKR)",
      id: "crm-lead-value",
      type: "number",
    },
    {
      name: "currency",
      label: "Currency",
      id: "crm-lead-currency",
      options: ["PKR"],
    },
    { name: "source", label: "Source", id: "crm-lead-source", max: 160 },
    {
      name: "expectedClose",
      label: "Expected Close",
      id: "crm-lead-close",
      type: "date",
    },
    {
      name: "status",
      label: "Status",
      id: "crm-lead-status",
      options: ["Active", "Inactive"],
    },
    {
      name: "ownerId",
      label: "Assign Salesperson",
      id: "crm-lead-owner",
      reference: "assignees",
    },
    { name: "notes", label: "Notes", id: "crm-lead-notes", max: 10000 },
  ],
  reminders: [
    {
      name: "leadId",
      label: "Lead",
      id: "crm-reminder-lead",
      reference: "leads",
    },
    {
      name: "type",
      label: "Type",
      id: "crm-reminder-type",
      options: ["Call", "Email", "Meeting", "Follow-up"],
    },
    {
      name: "dueDate",
      label: "Due Date",
      id: "crm-reminder-date",
      type: "date",
    },
    { name: "notes", label: "Notes", id: "crm-reminder-notes", max: 10000 },
    {
      name: "done",
      label: "Status",
      id: "crm-reminder-done",
      options: ["Open", "Done"],
    },
  ],
  vendors: [
    { name: "name", label: "Vendor Name", id: "vname", max: 160 },
    { name: "trn", label: "Tax Registration / NTN", id: "vtrn", max: 100 },
    { name: "contact", label: "Contact Person", id: "vcontact", max: 160 },
    { name: "phone", label: "Phone", id: "vphone", max: 80 },
    { name: "email", label: "Email", id: "vemail", type: "email", max: 254 },
    { name: "category", label: "Category", id: "vcat", max: 100 },
    {
      name: "status",
      label: "Status",
      id: "vstatus",
      options: ["Active", "Inactive"],
    },
  ],
  products: [
    { name: "name", label: "Product Name", id: "pname", max: 160 },
    { name: "sku", label: "SKU", id: "psku", max: 80 },
    { name: "category", label: "Category", id: "pcat", max: 100 },
    {
      name: "productType",
      label: "Product Type",
      id: "ptype",
      options: ["stock", "service"],
    },
    { name: "unit", label: "Unit", id: "punit", max: 40 },
    { name: "rate", label: "Default Rate (PKR)", id: "prate", type: "number" },
  ],
};
interface Page {
  items: MasterRecord[];
  total: number;
  page: number;
  pageSize: number;
}
export function MastersPage({
  kind,
  bridge,
  commands,
}: {
  kind: MasterKind;
  bridge: Bridge;
  commands: MasterCommands;
}) {
  const singular = {
    vendors: "Vendor",
    products: "Product",
    leads: "Lead",
    reminders: "Reminder",
  }[kind];
  const path =
    (kind === "leads" || kind === "reminders" ? "/crm/" : "/") + kind;
  const [data, setData] = useState<Page>({
    items: [],
    total: 0,
    page: 1,
    pageSize: 25,
  });
  const [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [editing, setEditing] = useState<MasterRecord | null | undefined>(
      undefined,
    ),
    [readonly, setReadonly] = useState(false);
  const [saving, setSaving] = useState(false),
    [formError, setFormError] = useState("");
  const form = useRef<HTMLFormElement>(null),
    dialog = useRef<HTMLDivElement>(null),
    busy = useRef(false),
    key = useRef("");
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    bridge
      .request<Page>(
        path +
          "?" +
          new URLSearchParams({ page: String(page), pageSize: "25", search }),
      )
      .then((result) => {
        if (active) {
          setData(result);
          bridge.cacheRecords(kind, result.items);
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
  }, [kind, page, search, reload, bridge]);
  useEffect(() => {
    if (editing === undefined || !dialog.current) return;
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const focusable = () =>
      Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
        ) || [],
      );
    focusable()[0]?.focus();
    const keyboard = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy.current) {
        e.preventDefault();
        setEditing(undefined);
      }
      if (e.key === "Tab") {
        const items = focusable(),
          first = items[0],
          last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    const current = dialog.current;
    current.addEventListener("keydown", keyboard);
    return () => {
      current.removeEventListener("keydown", keyboard);
      if (previous?.isConnected) previous.focus();
    };
  }, [editing === undefined]);
  const open = (value: MasterRecord | null, view = false) => {
    setFormError("");
    setReadonly(view);
    key.current =
      kind + "-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    setEditing(value);
  };
  const save = async () => {
    if (
      readonly ||
      busy.current ||
      !form.current ||
      !form.current.reportValidity()
    )
      return;
    const payload: Record<string, string | number | boolean> =
      Object.fromEntries(new FormData(form.current).entries()) as Record<
        string,
        string
      >;
    if (kind === "products") payload.rate = Number(payload.rate || 0);
    if (kind === "leads") {
      payload.value = Number(payload.value || 0);
      if (editing && !stages.includes(String(editing.stage)))
        delete payload.stage;
    }
    if (kind === "reminders") payload.done = payload.done === "Done";
    busy.current = true;
    setSaving(true);
    setFormError("");
    try {
      const result = await bridge.request<{ record: MasterRecord }>(
        path + (editing ? "/" + encodeURIComponent(String(editing.id)) : ""),
        {
          method: editing ? "PATCH" : "POST",
          body: JSON.stringify({
            ...payload,
            ...(editing
              ? { version: editing.version }
              : { requestKey: key.current }),
          }),
        },
      );
      bridge.cacheRecords(kind, [
        ...data.items.filter((r) => String(r.id) !== String(result.record.id)),
        result.record,
      ]);
      setEditing(undefined);
      setPage(1);
      setReload((v) => v + 1);
      bridge.toast(singular + (editing ? " updated" : " added"));
    } catch (e) {
      setFormError(errorMessage(e));
      if (
        typeof e === "object" &&
        e !== null &&
        "status" in e &&
        e.status === 409
      )
        setReload((v) => v + 1);
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };
  commands.open = (id) =>
    flushSync(() =>
      open(
        id === undefined
          ? null
          : data.items.find((r) => String(r.id) === String(id)) || null,
      ),
    );
  commands.save = save;
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void save();
  };
  const columns = fields[kind].filter(
    (f) =>
      !["productType", "notes", "ownerId", "currency", "email"].includes(
        f.name,
      ),
  );
  return (
    <>
      <div className="section-card" data-screen={kind + "-react"}>
        <div className="section-head">
          <div>
            <div className="section-title">
              {
                {
                  vendors: "Vendor List",
                  products: "Product Catalog",
                  leads: "Sales Leads",
                  reminders: "Follow-up Reminders",
                }[kind]
              }
            </div>
            <div className="hint">
              {kind === "leads"
                ? "Track opportunities and hand them to Sales"
                : kind === "reminders"
                  ? "Follow-ups for your permitted leads"
                  : "Shared master data · Pakistan · PKR"}
            </div>
          </div>
          {bridge.can(kind, "create") && (
            <button
              type="button"
              className="btn-primary"
              onClick={() => open(null)}
            >
              Add {singular}
            </button>
          )}
        </div>
        <form
          className="filters"
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(
              String(new FormData(e.currentTarget).get("search") || "").trim(),
            );
            setPage(1);
            setReload((v) => v + 1);
          }}
        >
          <input
            id={kind === "vendors" ? "vendor-search" : "product-search"}
            name="search"
            aria-label={"Search " + kind}
            placeholder={"Search " + kind}
            maxLength={160}
          />
          <button className="btn-secondary" type="submit">
            Search
          </button>
        </form>
        {error && (
          <p role="alert" className="modern-error">
            {error}{" "}
            <button type="button" onClick={() => setReload((v) => v + 1)}>
              Try again
            </button>
          </p>
        )}
        <div className="table-wrap" aria-busy={loading}>
          <table>
            <thead>
              <tr>
                {columns.map((f) => (
                  <th key={f.name}>{f.label}</th>
                ))}
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td className="empty" colSpan={columns.length + 1}>
                    Loading {kind}…
                  </td>
                </tr>
              ) : data.items.length ? (
                data.items.map((r) => (
                  <tr key={r.id}>
                    {columns.map((f) => (
                      <td key={f.name}>
                        {f.type === "number"
                          ? "Rs " +
                            Number(r[f.name] || 0).toLocaleString("en-PK", {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })
                          : String(
                              f.name === "customerId"
                                ? r.customerName
                                : f.name === "leadId"
                                  ? r.leadName
                                  : f.name === "done"
                                    ? r.done
                                      ? "Done"
                                      : "Open"
                                    : (r[f.name] ?? ""),
                            )}
                      </td>
                    ))}
                    <td>
                      <button
                        type="button"
                        className="btn-sm"
                        onClick={() => open(r, true)}
                      >
                        Details
                      </button>{" "}
                      {kind === "leads" &&
                        bridge.can("sales_quotations", "create") && (
                          <button
                            type="button"
                            className="btn-sm"
                            onClick={() =>
                              bridge.navigate(
                                "erp.html?view=sales-quotations&module=sales&leadId=" +
                                  encodeURIComponent(String(r.id)),
                              )
                            }
                          >
                            Open in Sales
                          </button>
                        )}{" "}
                      {bridge.can(kind, "edit") && (
                        <button
                          type="button"
                          className="btn-sm"
                          onClick={() => open(r)}
                        >
                          Edit
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="empty" colSpan={columns.length + 1}>
                    No {kind} found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="modern-pagination">
          <span>
            {data.total} {kind} · Page {page} of{" "}
            {Math.max(1, Math.ceil(data.total / data.pageSize))}
          </span>
          <div>
            <button
              className="btn-secondary"
              type="button"
              disabled={loading || page <= 1}
              onClick={() => setPage((v) => v - 1)}
            >
              Previous
            </button>
            <button
              className="btn-secondary"
              type="button"
              disabled={loading || page * data.pageSize >= data.total}
              onClick={() => setPage((v) => v + 1)}
            >
              Next
            </button>
          </div>
        </div>
      </div>
      {editing !== undefined && (
        <div className="modal" id="modal">
          <div
            className="modal-box request-modal"
            ref={dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="master-dialog-title"
          >
            <div className="modal-head">
              <h3 id="master-dialog-title">
                {readonly
                  ? singular + " Details"
                  : (editing ? "Edit " : "Add ") + singular}
              </h3>
              <button
                type="button"
                disabled={saving}
                aria-label="Close form"
                onClick={() => setEditing(undefined)}
              >
                ×
              </button>
            </div>
            <form ref={form} onSubmit={submit} key={editing?.version || "new"}>
              <div className="modal-body">
                <fieldset
                  className="modern-fieldset"
                  disabled={saving || readonly}
                >
                  <div className="grid2">
                    {fields[kind].map((f) => (
                      <label key={f.name}>
                        {f.label}
                        {f.reference ? (
                          <ReferenceField
                            field={f}
                            bridge={bridge}
                            editing={editing}
                            readonly={readonly}
                          />
                        ) : f.options ? (
                          <select
                            id={f.id}
                            name={f.name}
                            disabled={
                              kind === "leads" &&
                              f.name === "stage" &&
                              !!editing &&
                              !stages.includes(String(editing.stage))
                            }
                            defaultValue={String(
                              f.name === "done"
                                ? editing?.done
                                  ? "Done"
                                  : "Open"
                                : editing?.[f.name] || f.options[0],
                            )}
                          >
                            {(f.name === "stage" &&
                            editing?.stage &&
                            !stages.includes(String(editing.stage))
                              ? [...f.options, String(editing.stage)]
                              : f.options
                            ).map((o) => (
                              <option key={o} value={o}>
                                {o === "stock"
                                  ? "Goods — Track Inventory"
                                  : o === "service"
                                    ? "Service — No Stock"
                                    : o}
                              </option>
                            ))}
                          </select>
                        ) : f.name === "notes" ? (
                          <textarea
                            id={f.id}
                            name={f.name}
                            rows={3}
                            maxLength={f.max}
                            defaultValue={String(editing?.[f.name] || "")}
                          />
                        ) : (
                          <input
                            id={f.id}
                            name={f.name}
                            type={f.type || "text"}
                            required={
                              f.name === "name" ||
                              f.name === "unit" ||
                              f.name === "dueDate"
                            }
                            maxLength={f.max}
                            min={f.type === "number" ? 0 : undefined}
                            max={f.type === "number" ? 1e12 : undefined}
                            step={f.type === "number" ? "0.01" : undefined}
                            defaultValue={String(
                              editing?.[f.name] ??
                                (f.name === "unit"
                                  ? "Each"
                                  : f.name === "rate"
                                    ? 0
                                    : ""),
                            )}
                          />
                        )}
                      </label>
                    ))}
                  </div>
                </fieldset>
                {formError && (
                  <p role="alert" className="modern-error">
                    {formError} Close and reopen the record if it changed.
                  </p>
                )}
              </div>
              <div className="modal-foot">
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={saving}
                  onClick={() => setEditing(undefined)}
                >
                  {readonly ? "Close" : "Cancel"}
                </button>
                {!readonly && (
                  <button
                    type="submit"
                    className="btn-primary"
                    disabled={saving}
                  >
                    {saving ? "Saving…" : "Save"}
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

function ReferenceField({
  field,
  bridge,
  editing,
  readonly,
}: {
  field: Field;
  bridge: Bridge;
  editing: MasterRecord | null;
  readonly: boolean;
}) {
  const [items, setItems] = useState<MasterRecord[]>([]),
    [search, setSearch] = useState(""),
    [error, setError] = useState("");
  const [selected, setSelected] = useState(String(editing?.[field.name] || ""));
  const [label, setLabel] = useState(
    String(
      field.reference === "customers"
        ? editing?.customerName || ""
        : field.reference === "leads"
          ? editing?.leadName || ""
          : editing?.ownerId || "",
    ),
  );
  const reference = field.reference!;
  useEffect(() => {
    let active = true;
    setError("");
    const timer = setTimeout(() => {
      const endpoint =
        reference === "assignees"
          ? "/crm/assignees"
          : (reference === "leads" ? "/crm/leads" : "/customers") +
            "?" +
            new URLSearchParams({ page: "1", pageSize: "100", search });
      bridge
        .request<{ items: MasterRecord[] }>(endpoint)
        .then((result) => {
          if (active) setItems(result.items);
        })
        .catch((e) => {
          if (active) setError(errorMessage(e));
        });
    }, 150);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [reference, search, bridge]);
  return (
    <span className="modern-reference">
      {reference !== "assignees" && !readonly && (
        <input
          type="search"
          aria-label={"Find " + field.label.toLowerCase()}
          placeholder={"Find " + field.label.toLowerCase()}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          maxLength={160}
        />
      )}
      <select
        id={field.id}
        name={field.name}
        required={reference !== "assignees"}
        value={selected}
        onChange={(e) => {
          setSelected(e.target.value);
          const item = items.find((r) => String(r.id) === e.target.value);
          setLabel(String(item?.name || item?.customerName || ""));
          if (reference === "customers" && item) {
            const contact = document.getElementById(
                "crm-lead-contact",
              ) as HTMLInputElement | null,
              email = document.getElementById(
                "crm-lead-email",
              ) as HTMLInputElement | null;
            if (contact) contact.value = String(item.contact || "");
            if (email) email.value = String(item.email || "");
          }
        }}
      >
        <option value="">
          {reference === "assignees"
            ? "Keep with me / current owner"
            : "Select " + field.label.toLowerCase()}
        </option>
        {selected && !items.some((item) => String(item.id) === selected) && (
          <option value={selected}>{label || selected}</option>
        )}
        {items.map((item) => (
          <option key={item.id} value={item.id}>
            {String(item.name || item.customerName || item.id)}
          </option>
        ))}
      </select>
      {error && (
        <span role="alert" className="modern-error">
          {error}
        </span>
      )}
    </span>
  );
}
