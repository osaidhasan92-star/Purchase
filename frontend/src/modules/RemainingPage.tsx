import { useEffect, useRef, useState } from "react";
import type { Bridge, Workspace } from "../types";
import { Dialog } from "../components/Dialog";
import { Pager } from "./finance/FinanceReports";
import { Reference } from "./trade/Reference";
import {
  money,
  str,
  today,
  requestKey,
  type PageData,
  type Row,
} from "./finance/types";
import { errorMessage } from "../lib/api";
type View = "overview" | "companies" | "crmQuotes";
const descriptions: Record<string, string> = {
  crm: "Leads, customers and follow-ups.",
  sales: "Quotations, deliveries, invoices and collections.",
  purchase: "Requests, supplier quotes, receipts, bills and payments.",
  hr: "Employees, attendance, leave and payroll.",
  accounting: "Journals, reconciliation and financial reports.",
  inventory: "Stock balances, movements, adjustments and returns.",
  manufacturing: "Bills of materials, production and finished goods.",
  expenses: "Claims, receipts, approvals and reimbursements.",
  admin: "Accounts, roles, activity and record migration.",
};
export function RemainingPage({
  view,
  bridge,
  workspaces,
}: {
  view: View;
  bridge: Bridge;
  workspaces: Workspace[];
}) {
  const [data, setData] = useState<PageData>({
      items: [],
      total: 0,
      page: 1,
      pageSize: 25,
    }),
    [summary, setSummary] = useState<Record<string, unknown> | null>(null),
    [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState(""),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0),
    [form, setForm] = useState<Row | null | undefined>(undefined),
    [busy, setBusy] = useState(false);
  const locked = useRef(false);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(
      () =>
        bridge
          .request<PageData & Record<string, unknown>>(
            view === "overview"
              ? "/overview/summary"
              : "/crm-registers/" +
                  view +
                  "?" +
                  new URLSearchParams({
                    page: String(page),
                    pageSize: "25",
                    search,
                    status,
                  }),
          )
          .then((r) => {
            if (active) {
              if (view === "overview") setSummary(r);
              else setData(r);
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
  }, [view, bridge, page, search, status, reload]);
  async function edit(id: string | number) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      setForm(
        (
          await bridge.request<{ record: Row }>(
            "/crm-registers/" + view + "/" + encodeURIComponent(String(id)),
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
  async function seed() {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      await bridge.request("/erp/seed-demo", { method: "POST", body: "{}" });
      location.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <section data-native-remaining={view} aria-busy={loading}>
      {error && (
        <p role="alert" className="modern-error">
          {error}
        </p>
      )}
      {view === "overview" ? (
        <>
          {summary && (
            <div className="stats">
              {[
                ["cashBank", "Cash & Bank"],
                ["inventoryValue", "Inventory Value"],
                ["openProduction", "Open Production"],
                ["profit", "Net Profit"],
                ["pendingExpenses", "Pending Expenses"],
              ]
                .filter(([k]) => summary[k] !== undefined)
                .map(([k, t]) => (
                  <div className="stat-card finance-stat" key={k}>
                    <span>{t}</span>
                    <strong>
                      {["openProduction", "pendingExpenses"].includes(k)
                        ? str(summary[k])
                        : "PKR " + money(summary[k])}
                    </strong>
                  </div>
                ))}
            </div>
          )}
          <div className="erp-grid">
            {workspaces
              .filter((w) => w.id !== "overview")
              .map((w) => (
                <a className="erp-module" key={w.id} href={w.href}>
                  <i className={"ti " + w.icon} />
                  <h3>{w.label}</h3>
                  <p>{descriptions[w.id] || "Open workspace."}</p>
                </a>
              ))}
          </div>
          {!!summary?.canSeed && (
            <div className="section-card">
              <h3>General-products demonstration</h3>
              <p>
                Load sample products, a standard BoM, opening inventory and
                cash/bank balances into this empty installation. This posts demo
                opening journals.
              </p>
              <button className="btn-secondary" disabled={busy} onClick={seed}>
                Load demo opening data
              </button>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="section-head">
            <div>
              <h2>
                {view === "companies"
                  ? "Company and prospect directory"
                  : "Tracking quote register"}
              </h2>
              <p>
                {view === "companies"
                  ? "Shared CRM directory. Sales customers remain in Customers."
                  : "Historical CRM tracking only. Sales quotations control approval, orders and accounting."}
              </p>
            </div>
            {bridge.can(view, "create") && (
              <button
                className="btn-primary"
                disabled={busy}
                onClick={() => setForm(null)}
              >
                {view === "companies" ? "Add Company" : "New Tracking Quote"}
              </button>
            )}
          </div>
          <div className="finance-filters">
            <label>
              Search
              <input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Name or reference"
              />
            </label>
            <label>
              Status
              <select
                aria-label="Status"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All statuses</option>
                {(view === "companies"
                  ? ["Active", "Inactive"]
                  : ["Draft", "Sent", "Accepted", "Rejected", "Expired"]
                ).map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="finance-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {(view === "companies"
                    ? [
                        "Company",
                        "Industry",
                        "Contact",
                        "Email",
                        "Phone",
                        "Status",
                        "Actions",
                      ]
                    : [
                        "Reference",
                        "Company",
                        "Amount",
                        "Currency",
                        "Date",
                        "Valid until",
                        "Status",
                        "Actions",
                      ]
                  ).map((t) => (
                    <th key={t}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.id}>
                    {(view === "companies"
                      ? [
                          "name",
                          "industry",
                          "contact",
                          "email",
                          "phone",
                          "status",
                        ]
                      : [
                          "quoteNo",
                          "companyName",
                          "amount",
                          "currency",
                          "quoteDate",
                          "validUntil",
                          "status",
                        ]
                    ).map((k) => (
                      <td key={k}>
                        {k === "amount" ? money(r[k]) : str(r[k])}
                      </td>
                    ))}
                    <td>
                      <button
                        className="btn-secondary"
                        disabled={busy}
                        onClick={() => edit(r.id)}
                      >
                        {bridge.can(view, "edit") ? "Edit" : "View"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && !data.items.length && <p>No records found.</p>}
          </div>
          <Pager
            page={page}
            total={data.total}
            loading={loading}
            onPage={setPage}
          />
        </>
      )}
      {form !== undefined && view !== "overview" && (
        <RegisterForm
          view={view}
          bridge={bridge}
          record={form}
          onClose={() => setForm(undefined)}
          onSaved={() => {
            setForm(undefined);
            setReload((n) => n + 1);
          }}
        />
      )}
    </section>
  );
}
function RegisterForm({
  view,
  bridge,
  record,
  onClose,
  onSaved,
}: {
  view: "companies" | "crmQuotes";
  bridge: Bridge;
  record: Row | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [lead, setLead] = useState(String(record?.leadId || "")),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const lock = useRef(false),
    key = useRef(requestKey()),
    signature = useRef("");
  const editable = bridge.can(view, record ? "edit" : "create");
  async function save(form: HTMLFormElement) {
    if (lock.current || !editable) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const values: Record<string, unknown> = Object.fromEntries(
        new FormData(form),
      );
      if (view === "crmQuotes") values.leadId = lead;
      const next = JSON.stringify(values);
      if (signature.current && signature.current !== next)
        key.current = requestKey();
      signature.current = next;
      await bridge.request(
        "/crm-registers/" +
          view +
          (record ? "/" + encodeURIComponent(String(record.id)) : ""),
        {
          method: record ? "PATCH" : "POST",
          body: JSON.stringify({
            ...values,
            version: record?.version,
            requestKey: key.current,
          }),
        },
      );
      bridge.toast("CRM record saved");
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const title =
    view === "companies"
      ? record
        ? "Edit Company"
        : "Add Company"
      : record
        ? "Tracking Quote " + str(record.quoteNo)
        : "New Tracking Quote";
  return (
    <Dialog title={title} busy={busy} onClose={onClose}>
      <form
        className="trade-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save(e.currentTarget);
        }}
      >
        {error && (
          <p className="modern-error" role="alert">
            {error}
          </p>
        )}
        <fieldset disabled={busy || !editable} className="crm-register-fields">
          <div className="form-grid">
            {view === "companies" ? (
              <>
                {[
                  ["name", "Company name", 160],
                  ["industry", "Industry", 160],
                  ["contact", "Primary contact", 160],
                  ["email", "Email", 254],
                  ["phone", "Phone", 80],
                ].map(([k, t, max]) => (
                  <label key={String(k)}>
                    {t}
                    <input
                      name={String(k)}
                      type={k === "email" ? "email" : "text"}
                      required={k === "name"}
                      maxLength={Number(max)}
                      defaultValue={String(record?.[k] || "")}
                    />
                  </label>
                ))}
              </>
            ) : (
              <>
                <Reference
                  bridge={bridge}
                  path="/crm-registers/lead-options"
                  name="leadId"
                  label="Lead"
                  value={lead}
                  pinned={
                    record?.leadId
                      ? [
                          {
                            id: String(record.leadId),
                            name: str(record.companyName),
                          },
                        ]
                      : []
                  }
                  required
                  onSelect={(rows) => setLead(String(rows[0]?.id || ""))}
                />
                <label>
                  Amount
                  <input
                    name="amount"
                    type="number"
                    required
                    min="0.01"
                    step="0.01"
                    defaultValue={String(record?.amount || "")}
                  />
                </label>
                <label>
                  Currency
                  <select
                    aria-label="Currency"
                    name="currency"
                    defaultValue={String(record?.currency || "PKR")}
                  >
                    <option>PKR</option>
                    {!!record?.currency && record.currency !== "PKR" && (
                      <option>{str(record.currency)}</option>
                    )}
                  </select>
                </label>
                <label>
                  Quote date
                  <input
                    name="quoteDate"
                    type="date"
                    required
                    defaultValue={String(record?.quoteDate || today())}
                  />
                </label>
                <label>
                  Valid until
                  <input
                    name="validUntil"
                    type="date"
                    defaultValue={String(record?.validUntil || "")}
                  />
                </label>
              </>
            )}
            <label>
              Status
              <select
                aria-label="Status"
                name="status"
                defaultValue={String(
                  record?.status || (view === "companies" ? "Active" : "Draft"),
                )}
              >
                {(view === "companies"
                  ? ["Active", "Inactive"]
                  : ["Draft", "Sent", "Accepted", "Rejected", "Expired"]
                ).map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
          </div>
        </fieldset>
        {view === "crmQuotes" && (
          <p>
            This register does not send email, update the lead outcome, create a
            sales order or post a journal. Use Sales Quotations for the
            commercial workflow.
          </p>
        )}
        {view === "crmQuotes" && !!record?.salesHref && (
          <p>
            <a href={String(record.salesHref)}>
              Create Sales Quotation from Lead
            </a>
          </p>
        )}
        <div className="modal-foot">
          <button
            type="button"
            className="btn-secondary"
            disabled={busy}
            onClick={onClose}
          >
            Cancel
          </button>
          {editable && (
            <button className="btn-primary" disabled={busy}>
              Save
            </button>
          )}
        </div>
      </form>
    </Dialog>
  );
}
