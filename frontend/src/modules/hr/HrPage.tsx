import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Bridge } from "../../types";
import { Dialog } from "../../components/Dialog";
import { Reference } from "../trade/Reference";
import { errorMessage } from "../../lib/api";
import {
  configs,
  labels,
  keyFor,
  display,
  type Resource,
  type RecordData,
} from "./config";
type PageData = {
  items: RecordData[];
  total: number;
  page: number;
  pageSize: number;
};
export function HrPage({
  resource,
  bridge,
}: {
  resource: Resource;
  bridge: Bridge;
}) {
  const config = configs[resource];
  const [data, setData] = useState<PageData>({
      items: [],
      total: 0,
      page: 1,
      pageSize: 25,
    }),
    [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState(""),
    [reload, setReload] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [form, setForm] = useState<RecordData | null | undefined>(undefined),
    [detail, setDetail] = useState<RecordData | null>(null),
    [login, setLogin] = useState<RecordData | null>(null),
    [busy, setBusy] = useState(false);
  const locked = useRef(false),
    keys = useRef(new Map<string, string>());
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(() => {
      bridge
        .request<PageData>(
          "/hr/records/" +
            resource +
            "?" +
            new URLSearchParams({
              page: String(page),
              pageSize: "25",
              search,
              status,
            }),
        )
        .then((r) => {
          if (active) setData(r);
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
  }, [resource, bridge, page, search, status, reload]);
  async function open(row: RecordData, edit = false) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    try {
      const r = await bridge.request<{ record: RecordData }>(
        "/hr/records/" + resource + "/" + row.id,
      );
      if (edit) setForm(r.record);
      else setDetail(r.record);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  async function action(row: RecordData, action: string) {
    if (locked.current) return;
    if (action === "login") {
      setDetail(null);
      setLogin(row);
      return;
    }
    locked.current = true;
    setBusy(true);
    setError("");
    const slot = row.id + ":" + row.version + ":" + action;
    if (!keys.current.has(slot)) keys.current.set(slot, keyFor());
    try {
      await bridge.request(
        "/hr/records/" + resource + "/" + row.id + "/actions/" + action,
        {
          method: "POST",
          body: JSON.stringify({
            version: row.version,
            requestKey: keys.current.get(slot),
          }),
        },
      );
      setDetail(null);
      setReload((v) => v + 1);
      bridge.toast("HR record updated");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  const moneyFields = [
    "salary",
    "basic",
    "allowances",
    "deductions",
    "netPay",
    "finalSettlement",
  ];
  return (
    <section
      className="modern-customers"
      aria-busy={loading}
      data-native-hr={resource}
    >
      <div className="section-head">
        <div>
          <h2>{config.title}</h2>
          <p>
            {resource === "payroll"
              ? "Approval posts salary expense and liabilities. Record Payment clears salaries payable against Main Bank (PKR)."
              : resource === "separations"
                ? "Complete an approved exit to disable the linked login. The settlement field is an estimate; it creates no financial posting."
                : "Manage employee records and review workflow actions."}
          </p>
        </div>
        {bridge.can(config.module, "create") && (
          <button
            className="btn-primary"
            disabled={busy}
            onClick={() => setForm(null)}
          >
            Add{" "}
            {resource === "employees"
              ? "Employee"
              : resource === "candidates"
                ? "Candidate"
                : resource === "payroll"
                  ? "Payroll"
                  : resource === "attendance"
                    ? "Attendance"
                    : resource === "leaves"
                      ? "Leave Request"
                      : resource === "manpower"
                        ? "Manpower Request"
                        : "Separation"}
          </button>
        )}
      </div>
      <div className="modern-toolbar">
        <label>
          Search
          <input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            maxLength={160}
          />
        </label>
        <label>
          Status
          <input
            value={status}
            placeholder="All statuses"
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            maxLength={80}
          />
        </label>
        {["attendance", "payroll"].includes(resource) &&
          bridge.can(config.module, "export") && (
            <a
              className="btn-secondary"
              href={
                "/api/hr/records/" +
                resource +
                "/export?" +
                new URLSearchParams({
                  page: String(page),
                  pageSize: "25",
                  search,
                  status,
                })
              }
            >
              Export current page CSV
            </a>
          )}
      </div>
      {error && (
        <div className="modern-error" role="alert">
          {error}{" "}
          <button onClick={() => setReload((v) => v + 1)}>Try again</button>
        </div>
      )}
      {loading ? (
        <p role="status">Loading HR records…</p>
      ) : (
        <div className="modern-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                {config.columns.map((c) => (
                  <th key={c}>{labels[c] || c}</th>
                ))}
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={String(row.id)}>
                  {config.columns.map((c) => (
                    <td key={c}>
                      {moneyFields.includes(c)
                        ? Number(row[c] || 0).toLocaleString("en-PK", {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })
                        : display(row[c])}
                    </td>
                  ))}
                  <td>
                    <div className="hr-row-actions">
                      <button
                        className="btn-secondary btn-sm"
                        disabled={busy}
                        onClick={() => void open(row)}
                      >
                        View
                      </button>
                      {row.actions.includes("edit") && (
                        <button
                          className="btn-secondary btn-sm"
                          disabled={busy}
                          onClick={() => void open(row, true)}
                        >
                          Edit
                        </button>
                      )}
                      {row.actions
                        .filter((a) => a !== "edit")
                        .map((a) => (
                          <button
                            className="btn-secondary btn-sm"
                            key={a}
                            disabled={busy}
                            onClick={() => void action(row, a)}
                          >
                            {labels[a] || a}
                          </button>
                        ))}
                      {resource === "payroll" &&
                        ["Approved", "Paid"].includes(row.status) &&
                        bridge.can(config.module, "export") && (
                          <a
                            target="_blank"
                            rel="noopener"
                            href={
                              "/api/hr/records/payroll/" + row.id + "/print"
                            }
                          >
                            Print Payslip
                          </a>
                        )}
                    </div>
                  </td>
                </tr>
              ))}
              {!data.items.length && (
                <tr>
                  <td colSpan={config.columns.length + 1}>
                    No {config.title.toLowerCase()} found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <div className="modern-pagination">
        <button
          disabled={loading || page === 1}
          onClick={() => setPage((p) => p - 1)}
        >
          Previous
        </button>
        <span>
          Page {page} · {data.total} records
        </span>
        <button
          disabled={loading || page * 25 >= data.total}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
      </div>
      {form !== undefined && (
        <HrForm
          bridge={bridge}
          resource={resource}
          editing={form}
          onClose={() => setForm(undefined)}
          onSaved={() => {
            setForm(undefined);
            setReload((v) => v + 1);
          }}
        />
      )}
      {login && (
        <LoginForm
          bridge={bridge}
          row={login}
          onClose={() => setLogin(null)}
          onSaved={() => {
            setLogin(null);
            setReload((v) => v + 1);
          }}
        />
      )}
      {detail && (
        <Dialog
          title={config.title + " details"}
          busy={busy}
          onClose={() => setDetail(null)}
        >
          <div className="modern-detail">
            {Object.entries(detail)
              .filter(
                ([k, v]) =>
                  !["version", "actions"].includes(k) && typeof v !== "object",
              )
              .map(([k, v]) => (
                <p key={k}>
                  <b>{labels[k] || k}: </b>
                  {display(v)}
                </p>
              ))}
          </div>
          <div className="modal-foot">
            <button onClick={() => setDetail(null)}>Close</button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
function HrForm({
  resource,
  bridge,
  editing,
  onClose,
  onSaved,
}: {
  resource: Resource;
  bridge: Bridge;
  editing: RecordData | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const config = configs[resource];
  const today = new Date().toLocaleDateString("en-CA", {
    timeZone: "Asia/Karachi",
  });
  const [values, setValues] = useState<Record<string, unknown>>(() => ({
      joiningDate: today,
      date: today,
      month: today.slice(0, 7),
      salary: 0,
      basic: 0,
      allowances: 0,
      deductions: 0,
      finalSettlement: 0,
      count: 1,
      ...Object.fromEntries(
        config.fields
          .filter((f) => f.options)
          .map((f) => [f.key, f.options![0]]),
      ),
      ...editing,
    })),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const locked = useRef(false),
    requestKey = useRef(keyFor());
  const change = (key: string, value: unknown) =>
    setValues((v) => ({ ...v, [key]: value }));
  const fields = config.fields
    .filter(
      (f) =>
        (f.key !== "candidateId" || bridge.can("hr_recruitment", "approve")) &&
        (f.key !== "manpowerId" || bridge.can("hr_manpower")),
    )
    .filter((f) => !editing || !["candidateId", "manpowerId"].includes(f.key));
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      const payload: Record<string, unknown> = {
        requestKey: requestKey.current,
      };
      for (const f of fields) {
        if (editing && f.key === "employeeKey") continue;
        const v = values[f.key];
        if (v !== undefined && v !== "")
          payload[f.key] = f.type === "number" ? Number(v) : v;
      }
      if (editing) payload.version = editing.version;
      await bridge.request(
        "/hr/records/" + resource + (editing ? "/" + editing.id : ""),
        { method: editing ? "PATCH" : "POST", body: JSON.stringify(payload) },
      );
      bridge.toast("HR record saved");
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={(editing ? "Edit " : "Add ") + config.title}
      busy={busy}
      onClose={onClose}
    >
      <form onSubmit={(e) => void submit(e)} className="trade-form">
        <div className="form-grid">
          {fields.map((f) =>
            f.type === "employee" ||
            f.type === "candidate" ||
            f.type === "manpower" ? (
              <Reference
                key={f.key}
                bridge={bridge}
                path={
                  f.type === "employee"
                    ? "/hr/employee-options/" + resource
                    : f.type === "candidate"
                      ? "/hr/records/candidates?status=Offer%20Issued"
                      : "/hr/records/manpower?status=Approved"
                }
                name={f.key}
                label={f.label}
                value={String(values[f.key] || "")}
                disabled={busy || !!editing}
                required={f.required}
                onSelect={(items) => {
                  const item = items[0];
                  change(f.key, item?.id || "");
                  if (resource === "payroll" && item?.salary !== undefined)
                    change("basic", item.salary);
                }}
              />
            ) : (
              <label key={f.key}>
                {f.label}
                {f.options ? (
                  <select
                    name={f.key}
                    value={String(values[f.key] || "")}
                    disabled={busy}
                    onChange={(e) => change(f.key, e.target.value)}
                    required={f.required}
                  >
                    {f.options.map((o) => (
                      <option key={o}>{o}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    name={f.key}
                    type={f.type}
                    value={String(values[f.key] ?? "")}
                    disabled={busy}
                    onChange={(e) => change(f.key, e.target.value)}
                    required={f.required}
                    min={f.type === "number" ? "0" : undefined}
                    step={
                      f.key === "count"
                        ? "1"
                        : f.type === "number"
                          ? "0.01"
                          : undefined
                    }
                    maxLength={f.key === "reason" ? 4000 : 254}
                  />
                )}
              </label>
            ),
          )}
        </div>
        {resource === "payroll" && (
          <p>
            Estimated net pay: PKR{" "}
            {(
              Number(values.basic || 0) +
              Number(values.allowances || 0) -
              Number(values.deductions || 0)
            ).toFixed(2)}
            . Deductions are entered manually.
          </p>
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
          <button className="btn-primary" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function LoginForm({
  bridge,
  row,
  onClose,
  onSaved,
}: {
  bridge: Bridge;
  row: RecordData;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [roles, setRoles] = useState<string[]>([]);
  const key = useRef(keyFor()),
    locked = useRef(false);
  useEffect(() => {
    let active = true;
    bridge
      .request<{ state: { roles: Record<string, unknown> } }>("/ui/bootstrap")
      .then((r) => {
        if (active) setRoles(Object.keys(r.state.roles));
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [bridge]);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    const form = e.currentTarget;
    const d = Object.fromEntries(new FormData(form));
    try {
      await bridge.request(
        "/hr/records/employees/" + row.id + "/actions/login",
        {
          method: "POST",
          body: JSON.stringify({
            ...d,
            version: row.version,
            requestKey: key.current,
          }),
        },
      );
      form.reset();
      bridge.toast("Login created and linked");
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <Dialog title="Create Employee Login" busy={busy} onClose={onClose}>
      <form className="trade-form" onSubmit={(e) => void submit(e)}>
        <p>
          {display(row.name)} · {display(row.employeeId)}
        </p>
        <div className="form-grid">
          <label>
            Login email
            <input type="email" name="email" required disabled={busy} />
          </label>
          <label>
            System role
            <select name="role" required disabled={busy}>
              <option value="">Select role</option>
              {roles.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </label>
          <label>
            Initial password
            <input
              type="password"
              name="password"
              minLength={12}
              maxLength={256}
              autoComplete="new-password"
              required
              disabled={busy}
            />
          </label>
        </div>
        {error && (
          <p className="modern-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-foot">
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn-primary" disabled={busy}>
            Create Login
          </button>
        </div>
      </form>
    </Dialog>
  );
}
export function HrDashboard({
  bridge,
  reports = false,
}: {
  bridge: Bridge;
  reports?: boolean;
}) {
  const [data, setData] = useState<{
      registers: {
        key: Resource;
        count: number;
        statuses: Record<string, number>;
      }[];
      paidPayroll: number;
    } | null>(null),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    bridge
      .request<NonNullable<typeof data>>("/hr/summary")
      .then((r) => {
        if (active) setData(r);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [bridge, retry]);
  return (
    <section data-native-hr="dashboard">
      <h2>{reports ? "HR summaries" : "Employee lifecycle"}</h2>
      {error && (
        <p className="modern-error" role="alert">
          {error}{" "}
          <button onClick={() => setRetry((v) => v + 1)}>Try again</button>
        </p>
      )}
      {!data && !error && <p role="status">Loading HR summary…</p>}
      {data && (
        <>
          <div className="stats">
            {data.registers.map((r) => (
              <a
                className="stat-card"
                key={r.key}
                href={"erp.html?view=" + configs[r.key].view}
              >
                <h3>{configs[r.key].title}</h3>
                <strong>{r.count}</strong>
                <p>
                  {Object.entries(r.statuses)
                    .map(([s, n]) => s + ": " + n)
                    .join(" · ")}
                </p>
              </a>
            ))}
          </div>
          {bridge.can("hr_payroll") && (
            <p>
              Paid payroll total: PKR{" "}
              {data.paidPayroll.toLocaleString("en-PK", {
                minimumFractionDigits: 2,
              })}
            </p>
          )}
          <p>
            Recruitment → employees → attendance and leave → payroll approval →
            recorded payment.
          </p>
          {reports && (
            <p>
              Open Attendance or Payroll to search, filter and export each page.
              Report figures follow your record permissions.
            </p>
          )}
        </>
      )}
    </section>
  );
}
