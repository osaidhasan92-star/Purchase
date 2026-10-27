import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Bridge, User } from "../../types";
import { Dialog } from "../../components/Dialog";
import { errorMessage } from "../../lib/api";
import { Reference } from "./Reference";
import { LineEditor } from "./LineEditor";
import {
  configs,
  economicLines,
  keyFor,
  money,
  str,
  type Detail,
  type Resource,
  type TradeLine,
  type TradeRecord,
} from "./types";
const day = () =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Karachi" }).format(
    new Date(),
  );
const future = () => {
  const d = new Date(day() + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + 30);
  return d.toISOString().slice(0, 10);
};
interface Field {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  max?: number;
  options?: string[];
}
const fields: Partial<Record<Resource, Field[]>> = {
  requests: [
    { name: "date", label: "Request Date", type: "date", required: true },
    { name: "department", label: "Department", required: true, max: 160 },
    { name: "requester", label: "Requester", required: true, max: 160 },
    { name: "requiredDate", label: "Required Date", type: "date" },
    {
      name: "priority",
      label: "Priority",
      options: ["Normal", "High", "Urgent"],
    },
  ],
  rfqs: [
    {
      name: "dueDate",
      label: "Quotation Due Date",
      type: "date",
      required: true,
    },
  ],
  quotations: [
    { name: "quoteDate", label: "Quote Date", type: "date", required: true },
    { name: "validUntil", label: "Valid Until", type: "date", required: true },
    { name: "paymentTerms", label: "Payment Terms", max: 160 },
    { name: "deliveryTime", label: "Delivery Time", max: 160 },
  ],
  orders: [
    { name: "poDate", label: "PO Date", type: "date", required: true },
    {
      name: "deliveryDate",
      label: "Expected Delivery Date",
      type: "date",
      required: true,
    },
    { name: "deliveryLocation", label: "Delivery Location", max: 160 },
    { name: "paymentTerms", label: "Payment Terms", max: 160 },
    { name: "deliveryTerms", label: "Delivery Terms", max: 1000 },
  ],
  receipts: [
    {
      name: "receivedDate",
      label: "Receipt Date",
      type: "date",
      required: true,
    },
    { name: "receivedBy", label: "Received By", max: 160 },
    { name: "location", label: "Warehouse / Location", max: 160 },
  ],
  invoices: [
    {
      name: "invoiceNo",
      label: "Vendor Invoice Number",
      required: true,
      max: 160,
    },
    {
      name: "invoiceDate",
      label: "Invoice Date",
      type: "date",
      required: true,
    },
    { name: "dueDate", label: "Due Date", type: "date", required: true },
    { name: "referenceNo", label: "Reference", max: 160 },
  ],
  payments: [
    {
      name: "paymentDate",
      label: "Payment Date",
      type: "date",
      required: true,
    },
    {
      name: "amount",
      label: "Payment Amount (PKR)",
      type: "number",
      required: true,
    },
    {
      name: "method",
      label: "Method",
      options: ["Bank Transfer", "Cash", "Cheque", "Card", "Online"],
    },
    { name: "referenceNo", label: "Reference", max: 160 },
  ],
  salesQuotations: [
    {
      name: "quotationDate",
      label: "Quotation Date",
      type: "date",
      required: true,
    },
    { name: "validUntil", label: "Valid Until", type: "date" },
    { name: "paymentTerms", label: "Payment Terms", max: 160 },
    { name: "deliveryTerms", label: "Delivery Terms", max: 1000 },
    { name: "taxNote", label: "Tax Note", max: 1000 },
  ],
  salesOrders: [
    { name: "orderDate", label: "Order Date", type: "date", required: true },
  ],
  deliveries: [
    {
      name: "deliveryDate",
      label: "Delivery Date",
      type: "date",
      required: true,
    },
    { name: "deliveredBy", label: "Delivered By", max: 160 },
    { name: "referenceNo", label: "Challan Reference", max: 160 },
    { name: "location", label: "Warehouse / Location", max: 160 },
  ],
  customerInvoices: [
    {
      name: "invoiceDate",
      label: "Invoice Date",
      type: "date",
      required: true,
    },
    { name: "dueDate", label: "Due Date", type: "date", required: true },
  ],
  customerPayments: [
    {
      name: "paymentDate",
      label: "Payment Date",
      type: "date",
      required: true,
    },
    {
      name: "amount",
      label: "Payment Amount (PKR)",
      type: "number",
      required: true,
    },
    {
      name: "method",
      label: "Method",
      options: ["Bank Transfer", "Cash", "Cheque", "Card", "Online"],
    },
    { name: "referenceNo", label: "Reference", max: 160 },
  ],
};
const editNames = new Set([
  "department",
  "requester",
  "requiredDate",
  "priority",
  "paymentTerms",
  "deliveryTerms",
  "deliveryDate",
  "deliveryLocation",
  "validUntil",
  "taxNote",
  "deliveryTime",
]);
function initial(resource: Resource, user: User, editing?: TradeRecord) {
  const result: Record<string, string | number> = {};
  for (const field of fields[resource] || []) {
    result[field.name] = str(
      editing?.[field.name] ??
        (field.name === "dueDate" ||
        field.name === "validUntil" ||
        field.name === "deliveryDate"
          ? future()
          : field.type === "date"
            ? day()
            : field.name === "requester" ||
                field.name === "receivedBy" ||
                field.name === "deliveredBy"
              ? user.name
              : field.name === "location" || field.name === "deliveryLocation"
                ? "WH / Stock"
                : field.name === "paymentTerms"
                  ? "Cash"
                  : field.options?.[0] || ""),
    );
  }
  result.notes = str(editing?.notes);
  result.terms = str(editing?.terms);
  return result;
}
export function TradeForm({
  resource,
  bridge,
  user,
  editing,
  sourceId,
  leadId,
  onClose,
  onSaved,
}: {
  resource: Resource;
  bridge: Bridge;
  user: User;
  editing?: TradeRecord;
  sourceId?: string;
  leadId?: string;
  onClose: () => void;
  onSaved: (detail: Detail) => void;
}) {
  const config = configs[resource],
    sourceConfig = config.source;
  const [values, setValues] = useState(() => initial(resource, user, editing));
  const [source, setSource] = useState<Detail | null>(null),
    [sourceLoading, setSourceLoading] = useState(false),
    [error, setError] = useState(""),
    [saving, setSaving] = useState(false);
  const [partner, setPartner] = useState(
      str(editing?.customerId || editing?.vendorId),
    ),
    [lead, setLead] = useState<TradeRecord | null>(null);
  const [vendors, setVendors] = useState<
    { id: string | number; name?: string }[]
  >([]);
  const [lines, setLines] = useState<TradeLine[]>(() =>
    editing
      ? economicLines(editing)
      : ["requests", "salesQuotations", "orders"].includes(resource)
        ? [{ quantity: 1, rate: 0, taxPercent: 0, discountPercent: 0 }]
        : [],
  );
  const busy = useRef(false),
    requestKey = useRef(keyFor("trade-" + resource)),
    form = useRef<HTMLFormElement>(null),
    sourceGeneration = useRef(0),
    file = useRef<HTMLInputElement>(null),
    uploaded = useRef<{ attachmentPath: string; attachment: string } | null>(
      null,
    );
  const loadSource = async (identity: string) => {
    const generation = ++sourceGeneration.current;
    setSource(null);
    setError("");
    if (!identity || !sourceConfig) {
      if (resource === "orders")
        setLines([{ quantity: 1, rate: 0, taxPercent: 0, discountPercent: 0 }]);
      return;
    }
    setSourceLoading(true);
    try {
      const detail = await bridge.request<Detail>(
        "/trade/" + sourceConfig.resource + "/" + encodeURIComponent(identity),
      );
      if (generation !== sourceGeneration.current) return;
      setSource(detail);
      if (detail.record.paymentTerms)
        setValues((old) => ({
          ...old,
          paymentTerms: str(detail.record.paymentTerms),
        }));
      if (
        resource === "rfqs" ||
        resource === "quotations" ||
        resource === "salesOrders" ||
        resource === "orders"
      )
        setLines(
          economicLines(detail.record).map((line) => ({
            ...line,
            rate: Number(line.rate ?? line.quotedRate ?? 0),
          })),
        );
      if (
        ["receipts", "deliveries", "invoices", "customerInvoices"].includes(
          resource,
        )
      )
        setLines(
          (detail.context.lines || []).map((line) => ({
            ...line,
            quantity:
              resource === "invoices"
                ? Math.min(line.invoiceRemaining, line.acceptedUnbilled)
                : line.invoiceRemaining,
            receivedQty: line.remaining,
            acceptedQty: line.remaining,
            rejectedQty: 0,
            deliveredQty: line.remaining,
            inspection: "Accepted",
          })),
        );
      if (resource === "payments" || resource === "customerPayments")
        setValues((old) => ({
          ...old,
          amount: Number(
            detail.context.balance ??
              detail.record.balance ??
              Number(detail.record.amount || 0) -
                Number(detail.record.paidAmount || 0),
          ),
        }));
      if (resource === "quotations") {
        const first = detail.record.vendors?.[0];
        setPartner(str(first?.id));
      }
    } catch (e) {
      if (generation === sourceGeneration.current) setError(errorMessage(e));
    } finally {
      if (generation === sourceGeneration.current) setSourceLoading(false);
    }
  };
  useEffect(() => {
    let active = true;
    if (sourceId && !editing) void loadSource(sourceId);
    if (leadId && !editing && resource === "salesQuotations") {
      setSourceLoading(true);
      bridge
        .request<{ record: TradeRecord }>(
          "/trade/reference/leads/" + encodeURIComponent(leadId),
        )
        .then((result) => {
          if (active) {
            setLead(result.record);
            setPartner(str(result.record.customerId));
          }
        })
        .catch((e) => {
          if (active) setError(errorMessage(e));
        })
        .finally(() => {
          if (active) setSourceLoading(false);
        });
    }
    return () => {
      active = false;
      sourceGeneration.current++;
    };
  }, []);
  const set = (name: string, value: string | number) =>
    setValues((old) => ({ ...old, [name]: value }));
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy.current || sourceLoading || !form.current?.reportValidity())
      return;
    setError("");
    busy.current = true;
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        requestKey: requestKey.current,
      };
      for (const field of fields[resource] || []) {
        if (editing && !editNames.has(field.name)) continue;
        payload[field.name] =
          field.type === "number"
            ? Number(values[field.name] || 0)
            : values[field.name] || "";
      }
      payload.notes = values.notes || "";
      if (resource === "orders" || resource === "salesQuotations")
        payload.terms = values.terms || "";
      if (!editing && sourceConfig) {
        if (!source && resource !== "orders")
          throw new Error("Select a source document first.");
        if (source) {
          payload[sourceConfig.field] = source.record.id;
          payload.parentVersion = source.record.version;
        }
      }
      if (!editing && resource === "rfqs")
        payload.vendorIds = vendors.map((v) => v.id);
      if (!editing && resource === "quotations") payload.vendorId = partner;
      if (!editing && resource === "orders" && !source)
        payload.vendorId = partner;
      if (!editing && resource === "salesQuotations") {
        payload.customerId = partner;
        if (lead) {
          payload.leadId = lead.id;
          payload.parentVersion = lead.version;
        }
      }
      const priced =
        ["requests", "salesQuotations", "quotations"].includes(resource) ||
        (resource === "orders" && !source && !editing?.quotationId);
      if (priced)
        payload.items = lines.map((line) => ({
          productId: line.productId,
          quantity: Number(line.quantity || 0),
          rate: Number(line.rate ?? line.quotedRate ?? 0),
          discountPercent: Number(line.discountPercent || 0),
          taxPercent: Number(line.taxPercent || 0),
          description: str(line.description),
        }));
      if (resource === "receipts")
        payload.items = lines.map((line, index) => ({
          lineIndex: line.lineIndex ?? index,
          receivedQty: Number(line.receivedQty || 0),
          acceptedQty: Number(line.acceptedQty || 0),
          rejectedQty: Number(line.rejectedQty || 0),
          inspection: str(line.inspection) || "Accepted",
          remark: str(line.remark),
        }));
      if (resource === "deliveries")
        payload.items = lines
          .filter((line) => Number(line.deliveredQty) > 0)
          .map((line, index) => ({
            lineIndex: line.lineIndex ?? index,
            deliveredQty: Number(line.deliveredQty),
          }));
      if (resource === "invoices" || resource === "customerInvoices")
        payload.items = lines
          .filter((line) => Number(line.quantity) > 0)
          .map((line, index) => ({
            lineIndex: line.lineIndex ?? index,
            quantity: Number(line.quantity),
          }));
      if (editing) payload.version = editing.version;
      if (!editing && file.current?.files?.[0]) {
        if (!uploaded.current) {
          const data = new FormData();
          data.append("file", file.current.files[0]);
          data.append("module", resource);
          const result = await bridge.request<{
            attachmentPath: string;
            name: string;
          }>("/attachments", { method: "POST", body: data });
          uploaded.current = {
            attachmentPath: result.attachmentPath,
            attachment: result.name,
          };
        }
        Object.assign(payload, uploaded.current);
      }
      const result = await bridge.request<Detail>(
        "/trade/" +
          resource +
          (editing ? "/" + encodeURIComponent(String(editing.id)) : ""),
        { method: editing ? "PATCH" : "POST", body: JSON.stringify(payload) },
      );
      onSaved(result);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };
  const showLines = [
    "requests",
    "salesQuotations",
    "quotations",
    "orders",
    "salesOrders",
    "receipts",
    "deliveries",
    "invoices",
    "customerInvoices",
  ].includes(resource);
  const locked =
    resource === "salesOrders" ||
    (resource === "orders" && (!!source || !!editing?.quotationId));
  return (
    <Dialog
      title={(editing ? "Edit " : "New ") + config.singular}
      busy={saving}
      onClose={onClose}
    >
      <form ref={form} onSubmit={(event) => void submit(event)}>
        <div className="modal-body">
          <fieldset className="modern-fieldset" disabled={saving}>
            {!editing && sourceConfig && (
              <>
                <Reference
                  bridge={bridge}
                  path={
                    "/trade/" +
                    sourceConfig.resource +
                    "?status=" +
                    encodeURIComponent(sourceConfig.status)
                  }
                  label={sourceConfig.label}
                  name={sourceConfig.field}
                  required={resource !== "orders"}
                  value={source ? String(source.record.id) : ""}
                  pinned={source ? [source.record] : []}
                  onSelect={(items) =>
                    void loadSource(items[0] ? String(items[0].id) : "")
                  }
                />
                {source && (
                  <p className="hint">
                    {str(source.record[configs[sourceConfig.resource].number])}{" "}
                    ·{" "}
                    {str(
                      source.record.customerName || source.record.vendorName,
                    )}{" "}
                    · {money(source.record.amount ?? source.record.total)} ·{" "}
                    {source.record.status}
                  </p>
                )}
              </>
            )}
            {!editing && resource === "salesQuotations" && (
              <div className="grid2">
                <Reference
                  bridge={bridge}
                  path="/crm/leads"
                  label="CRM Lead (optional)"
                  name="leadId"
                  value={lead ? String(lead.id) : ""}
                  pinned={lead ? [lead] : []}
                  onSelect={(items) => {
                    const selected = items[0];
                    setLead(selected ? (selected as TradeRecord) : null);
                    if (selected) setPartner(str(selected.customerId));
                  }}
                />
                <Reference
                  bridge={bridge}
                  path="/customers"
                  label="Customer"
                  name="customerId"
                  required
                  value={partner}
                  pinned={
                    lead && partner
                      ? [{ id: partner, name: str(lead.customerName) }]
                      : []
                  }
                  onSelect={(items) =>
                    setPartner(items[0] ? String(items[0].id) : "")
                  }
                />
              </div>
            )}
            {!editing && resource === "rfqs" && (
              <Reference
                bridge={bridge}
                path="/vendors"
                label="Invited Vendors"
                name="vendorIds"
                value={vendors.map((v) => String(v.id))}
                multiple
                required
                pinned={vendors}
                onSelect={(items) =>
                  setVendors(
                    items.map((item) => ({
                      id: item.id,
                      name: str(item.name),
                    })),
                  )
                }
              />
            )}
            {!editing && resource === "quotations" && (
              <label>
                Invited Vendor
                <select
                  aria-label="Invited Vendor"
                  name="vendorId"
                  required
                  value={partner}
                  onChange={(e) => setPartner(e.target.value)}
                >
                  <option value="">Select vendor…</option>
                  {(Array.isArray(source?.record.vendors)
                    ? source.record.vendors
                    : []
                  ).map((vendor) => (
                    <option key={vendor.id} value={String(vendor.id)}>
                      {vendor.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {!editing && resource === "orders" && !source && (
              <Reference
                bridge={bridge}
                path="/vendors"
                label="Vendor for Direct PO"
                name="vendorId"
                required
                value={partner}
                onSelect={(items) =>
                  setPartner(items[0] ? String(items[0].id) : "")
                }
              />
            )}
            {editing && (
              <p className="hint">
                {str(editing[config.number])} ·{" "}
                {str(editing.customerName || editing.vendorName)} ·{" "}
                {editing.status}. Source and partner remain fixed.
              </p>
            )}
            <div className="grid2">
              {(fields[resource] || [])
                .filter((f) => !editing || editNames.has(f.name))
                .map((field) => (
                  <label key={field.name}>
                    {field.label}
                    {field.options ? (
                      <select
                        name={field.name}
                        value={str(values[field.name])}
                        onChange={(e) => set(field.name, e.target.value)}
                      >
                        {field.options.map((option) => (
                          <option key={option}>{option}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        name={field.name}
                        aria-label={field.label}
                        required={field.required}
                        type={field.type || "text"}
                        maxLength={field.max || 1000}
                        min={field.type === "number" ? "0.01" : undefined}
                        step={field.type === "number" ? "0.01" : undefined}
                        max={
                          field.type === "number"
                            ? Number(
                                source?.context.balance ??
                                  source?.record.balance ??
                                  1e12,
                              )
                            : undefined
                        }
                        value={values[field.name] ?? ""}
                        onChange={(e) => set(field.name, e.target.value)}
                      />
                    )}
                  </label>
                ))}
            </div>
            {(resource === "payments" || resource === "customerPayments") &&
              source && (
                <p className="detail-note">
                  Outstanding balance:{" "}
                  <b>
                    {money(
                      source.context.balance ??
                        source.record.balance ??
                        Number(source.record.amount || 0) -
                          Number(source.record.paidAmount || 0),
                    )}
                  </b>
                  . Saving records and posts this payment automatically.
                </p>
              )}
            {sourceLoading && <p role="status">Loading source document…</p>}
            {showLines && (
              <LineEditor
                bridge={bridge}
                resource={resource}
                lines={lines}
                onChange={setLines}
                locked={locked || sourceLoading || resource === "rfqs"}
                priced={!["receipts", "deliveries"].includes(resource)}
              />
            )}
            {resource === "invoices" && (
              <p className="hint">
                Bills are matched against accepted receipts. Quantities not
                received create a match exception and cannot be approved until
                resolved.
              </p>
            )}
            {!!source?.context.legacyInvoiceCount && (
              <p className="detail-note">
                Older bills on this order have no line allocations. Check the
                prior bills before choosing quantities; the server enforces the
                remaining received value.
              </p>
            )}
            <label>
              Notes
              <textarea
                name="notes"
                rows={3}
                maxLength={10000}
                value={str(values.notes)}
                onChange={(e) => set("notes", e.target.value)}
              />
            </label>
            {(resource === "orders" || resource === "salesQuotations") && (
              <label>
                Terms and Conditions
                <textarea
                  name="terms"
                  rows={3}
                  maxLength={10000}
                  value={str(values.terms)}
                  onChange={(e) => set("terms", e.target.value)}
                />
              </label>
            )}
            {!editing &&
              ["requests", "quotations", "orders"].includes(resource) && (
                <label>
                  PDF Attachment
                  <input
                    ref={file}
                    name="attachment"
                    type="file"
                    accept="application/pdf"
                  />
                </label>
              )}
          </fieldset>
          {error && (
            <p role="alert" className="modern-error">
              {error} If a document changed, close and reopen this form to
              refresh its version.
            </p>
          )}
        </div>
        <div className="modal-foot">
          <button
            type="button"
            className="btn-secondary"
            disabled={saving}
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn-primary"
            disabled={saving || sourceLoading}
          >
            {saving
              ? "Saving…"
              : editing
                ? "Save Changes"
                : resource === "payments" || resource === "customerPayments"
                  ? "Record Payment"
                  : resource === "customerInvoices"
                    ? "Post Invoice"
                    : "Save " + config.singular}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
