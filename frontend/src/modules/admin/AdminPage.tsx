import { useEffect, useRef, useState } from "react";
import type { Bridge, User } from "../../types";
import { Dialog } from "../../components/Dialog";
import { Pager } from "../finance/FinanceReports";
import { requestKey, str, type PageData, type Row } from "../finance/types";
import { errorMessage } from "../../lib/api";
import { Reference } from "../trade/Reference";
interface Account extends User {
  email: string;
  active: boolean;
  version: string;
}
interface Role {
  name: string;
  version: string;
  permissions: Record<string, Record<string, boolean>>;
}
interface Config {
  items: { name: string; version: string }[];
  modules: string[];
  actions: string[];
}
type Form =
  | { kind: "create-user" }
  | { kind: "edit-user" | "password"; record: Account }
  | { kind: "role"; record: Role };
export function AdminPage({
  view,
  bridge,
  user,
}: {
  view: "users" | "activities" | "data";
  bridge: Bridge;
  user: User;
}) {
  const [data, setData] = useState<PageData>({
      items: [],
      page: 1,
      pageSize: 25,
      total: 0,
    }),
    [summary, setSummary] = useState<Record<string, number>>({}),
    [config, setConfig] = useState<Config | null>(null),
    [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [active, setActive] = useState(""),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [reload, setReload] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [form, setForm] = useState<Form | null>(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    if (view === "data") {
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(
      () =>
        Promise.all([
          bridge.request<PageData>(
            "/administration/" +
              view +
              "?" +
              new URLSearchParams({
                page: String(page),
                pageSize: "25",
                search,
                active,
                from: start,
                to: end,
              }),
          ),
          view === "users"
            ? bridge.request<Record<string, number>>("/administration/summary")
            : Promise.resolve({}),
          view === "users"
            ? bridge.request<Config>("/administration/roles")
            : Promise.resolve(null),
        ])
          .then(([d, s, c]) => {
            if (live) {
              setData(d);
              setSummary(s);
              setConfig(c);
            }
          })
          .catch((e) => {
            if (live) setError(errorMessage(e));
          })
          .finally(() => {
            if (live) setLoading(false);
          }),
      150,
    );
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [view, bridge, page, search, active, start, end, reload]);
  async function open(kind: "edit-user" | "password" | "role", id: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (kind === "role")
        setForm({
          kind,
          record: (
            await bridge.request<{ record: Role }>(
              "/administration/roles/" + encodeURIComponent(id),
            )
          ).record,
        });
      else
        setForm({
          kind,
          record: (
            await bridge.request<{ record: Account }>(
              "/administration/users/" + encodeURIComponent(id),
            )
          ).record,
        });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section data-native-admin={view} aria-busy={loading}>
      <div className="section-head">
        <div>
          <h2>
            {view === "users"
              ? "Account and role management"
              : view === "activities"
                ? "Recorded activity"
                : "Import / Export Records"}
          </h2>
          <p>
            {view === "users"
              ? "Assign roles and direct team managers"
              : view === "activities"
                ? user.role === "Admin"
                  ? "All users · server audit events"
                  : "Your own server audit events"
                : "Administrator migration tools"}
          </p>
        </div>
        {view === "users" && (
          <button
            className="btn-primary"
            disabled={busy || !config}
            onClick={() => setForm({ kind: "create-user" })}
          >
            Add User
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="modern-error">
          {error}
        </p>
      )}
      {view === "data" ? (
        <DataTools bridge={bridge} />
      ) : (
        <>
          {view === "users" && (
            <div className="stats">
              {[
                ["users", "Total users"],
                ["active", "Active users"],
                ["admins", "Active administrators"],
                ["roles", "Roles"],
              ].map(([k, t]) => (
                <div className="stat-card finance-stat" key={k}>
                  <span>{t}</span>
                  <strong>{summary[k] || 0}</strong>
                </div>
              ))}
            </div>
          )}
          <div className="finance-filters">
            <label>
              Search
              <input
                aria-label="Search"
                value={search}
                placeholder={
                  view === "users" ? "Name, email or role" : "Actor or action"
                }
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </label>
            {view === "users" ? (
              <label>
                Status
                <select
                  aria-label="Status"
                  value={active}
                  onChange={(e) => {
                    setActive(e.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">All users</option>
                  <option value="true">Active</option>
                  <option value="false">Inactive</option>
                </select>
              </label>
            ) : (
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
              </>
            )}
          </div>
          <div className="finance-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {(view === "users"
                    ? [
                        "Name",
                        "Email",
                        "Role",
                        "Team manager",
                        "Status",
                        "Actions",
                      ]
                    : ["Time (UTC)", "Actor", "Action", "Details"]
                  ).map((t) => (
                    <th key={t}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) =>
                  view === "users" ? (
                    <tr key={r.id}>
                      <td>{str(r.name)}</td>
                      <td>{str(r.email)}</td>
                      <td>{str(r.role)}</td>
                      <td>{str(r.managerName)}</td>
                      <td>{r.active ? "Active" : "Inactive"}</td>
                      <td>
                        <div className="finance-actions">
                          <button
                            className="btn-secondary"
                            disabled={busy}
                            onClick={() => open("edit-user", String(r.id))}
                          >
                            Edit
                          </button>
                          <button
                            className="btn-secondary"
                            disabled={busy}
                            onClick={() => open("password", String(r.id))}
                          >
                            Reset Password
                          </button>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    <tr key={r.id}>
                      <td>{str(r.at)}</td>
                      <td>{str(r.actor)}</td>
                      <td>{str(r.action)}</td>
                      <td className="admin-audit-details">
                        {JSON.stringify(r.details)}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
            {!loading && !data.items.length && (
              <p>No {view === "users" ? "users" : "activities"} found.</p>
            )}
          </div>
          <Pager
            page={page}
            total={data.total}
            loading={loading}
            onPage={setPage}
          />
          {view === "users" && config && (
            <div className="section-card">
              <div className="section-head">
                <div>
                  <h3>Roles & Permissions</h3>
                  <p>
                    Admin access is fixed. Editing another role signs its users
                    out.
                  </p>
                </div>
              </div>
              <div className="finance-actions">
                {config.items.map((r) => (
                  <button
                    className="btn-secondary"
                    key={r.name}
                    disabled={busy || r.name === "Admin"}
                    onClick={() => open("role", r.name)}
                  >
                    {r.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      {form && config && (
        <AdminForm
          form={form}
          config={config}
          bridge={bridge}
          user={user}
          onClose={() => setForm(null)}
          onSaved={() => {
            setForm(null);
            setReload((n) => n + 1);
          }}
        />
      )}
    </section>
  );
}
function AdminForm({
  form,
  config,
  bridge,
  user,
  onClose,
  onSaved,
}: {
  form: Form;
  config: Config;
  bridge: Bridge;
  user: User;
  onClose: () => void;
  onSaved: () => void;
}) {
  const account =
      form.kind === "edit-user" || form.kind === "password"
        ? form.record
        : null,
    role = form.kind === "role" ? form.record : null;
  const [manager, setManager] = useState(account?.managerId || ""),
    [permissions, setPermissions] = useState(role?.permissions || {}),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const lock = useRef(false),
    key = useRef(requestKey()),
    signature = useRef("");
  async function save(el: HTMLFormElement) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const d: Record<string, unknown> =
        form.kind === "role"
          ? { name: role!.name, version: role!.version, permissions }
          : Object.fromEntries(new FormData(el));
      if (account) {
        d.id = account.id;
        d.version = account.version;
      }
      if (form.kind !== "password" && form.kind !== "role") {
        d.active = (
          el.elements.namedItem("active") as HTMLInputElement
        ).checked;
        d.managerId = manager || null;
      }
      const next = JSON.stringify(d);
      if (signature.current && signature.current !== next)
        key.current = requestKey();
      signature.current = next;
      const r = await bridge.request<{ signInRequired: boolean }>(
        "/administration/commands/" + form.kind,
        {
          method: "POST",
          body: JSON.stringify({ ...d, requestKey: key.current }),
        },
      );
      if (r.signInRequired) {
        location.assign("index.html");
        return;
      }
      bridge.toast("Administration change saved");
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const title =
    form.kind === "create-user"
      ? "Add User"
      : form.kind === "password"
        ? "Reset Password"
        : role
          ? role.name + " Permissions"
          : "Edit User";
  return (
    <Dialog title={title} busy={busy} onClose={onClose}>
      <form
        className="trade-form admin-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save(e.currentTarget);
        }}
      >
        {error && (
          <p role="alert" className="modern-error">
            {error}
          </p>
        )}
        {account?.id === user.id && (
          <p>
            Saving changes to your account signs you out. You cannot deactivate
            or demote your own administrator account.
          </p>
        )}
        {role ? (
          <>
            <p>
              View controls module access. Unchecking View clears every action
              for that module.
            </p>
            <div className="finance-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Module</th>
                    {config.actions.map((a) => (
                      <th key={a}>{a}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {config.modules.map((m) => (
                    <tr key={m}>
                      <td>{m.replaceAll("_", " ")}</td>
                      {config.actions.map((a) => (
                        <td key={a}>
                          <input
                            type="checkbox"
                            aria-label={m + " " + a}
                            checked={!!permissions[m]?.[a]}
                            disabled={
                              busy || (a !== "view" && !permissions[m]?.view)
                            }
                            onChange={(e) =>
                              setPermissions((old) => ({
                                ...old,
                                [m]:
                                  a === "view" && !e.target.checked
                                    ? Object.fromEntries(
                                        config.actions.map((k) => [k, false]),
                                      )
                                    : { ...old[m], [a]: e.target.checked },
                              }))
                            }
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <>
            {form.kind !== "password" && (
              <div className="form-grid">
                <label>
                  Name
                  <input
                    name="name"
                    required
                    maxLength={160}
                    defaultValue={account?.name}
                  />
                </label>
                <label>
                  Email
                  <input
                    name="email"
                    type="email"
                    required
                    maxLength={254}
                    defaultValue={account?.email}
                  />
                </label>
                <label>
                  Role
                  <select
                    aria-label="Role"
                    name="role"
                    defaultValue={account?.role || "Viewer"}
                  >
                    {config.items.map((r) => (
                      <option key={r.name}>{r.name}</option>
                    ))}
                  </select>
                </label>
                <Reference
                  bridge={bridge}
                  path={
                    "/administration/managers?exclude=" +
                    encodeURIComponent(account?.id || "")
                  }
                  label="Team manager"
                  name="managerId"
                  value={manager}
                  pinned={manager ? [{ id: manager, name: manager }] : []}
                  onSelect={(rows) => setManager(String(rows[0]?.id || ""))}
                />
                <label className="admin-active">
                  <input
                    name="active"
                    type="checkbox"
                    defaultChecked={account?.active !== false}
                  />{" "}
                  Active user
                </label>
              </div>
            )}
            {(form.kind === "create-user" || form.kind === "password") && (
              <div className="form-grid">
                <label>
                  New password
                  <input
                    name="password"
                    type="password"
                    required
                    minLength={12}
                    maxLength={256}
                    autoComplete="new-password"
                  />
                </label>
                {form.kind === "password" && (
                  <label>
                    Confirm password
                    <input
                      name="confirmPassword"
                      type="password"
                      required
                      minLength={12}
                      maxLength={256}
                      autoComplete="new-password"
                    />
                  </label>
                )}
              </div>
            )}
            {form.kind === "password" && (
              <p>
                This resets {account?.email} and revokes all sessions for that
                account.
              </p>
            )}
          </>
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
          <button className="btn-primary" disabled={busy}>
            {role
              ? "Save Permissions"
              : form.kind === "password"
                ? "Reset Password"
                : "Save User"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function stripCredentials(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(stripCredentials);
  if (v && typeof v === "object")
    return Object.fromEntries(
      Object.entries(v)
        .filter(
          ([k]) =>
            ![
              "password",
              "password_hash",
              "initialpassword",
              "currentpassword",
              "newpassword",
              "confirmpassword",
            ].includes(k.toLowerCase()),
        )
        .map(([k, x]) => [k, stripCredentials(x)]),
    );
  return v;
}
function DataTools({ bridge }: { bridge: Bridge }) {
  const [busy, setBusy] = useState(false),
    [result, setResult] = useState(""),
    [error, setError] = useState("");
  const file = useRef<HTMLInputElement>(null),
    lock = useRef(false);
  async function run(kind: "export" | "file" | "browser") {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setResult("");
    try {
      if (kind === "export") {
        const data = await bridge.request("/admin/export");
        const url = URL.createObjectURL(
            new Blob([JSON.stringify(data, null, 2)], {
              type: "application/json",
            }),
          ),
          a = document.createElement("a");
        a.href = url;
        a.download =
          "purchase-records-" + new Date().toISOString().slice(0, 10) + ".json";
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        setResult("Operational records exported.");
      } else {
        let data: unknown;
        if (kind === "file") {
          const selected = file.current?.files?.[0];
          if (!selected) throw new Error("Select a JSON file");
          if (selected.size > 10 * 1024 * 1024)
            throw new Error("Select a JSON file up to 10 MB");
          data = JSON.parse(await selected.text());
        } else {
          const app = JSON.parse(
            localStorage.getItem("purchase_demo_state_v1") || "null",
          );
          if (!app)
            throw new Error("No old demo records found in this browser");
          data = {
            app,
            hr: JSON.parse(
              localStorage.getItem("unified_hr_payroll_v1") || "{}",
            ),
          };
        }
        const r = await bridge.request<{ message: string }>("/admin/import", {
          method: "POST",
          body: JSON.stringify(stripCredentials(data)),
        });
        setResult(r.message);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="section-card">
      <p>
        Import is available only on an empty installation. Imported accounts
        remain disabled until an administrator resets their passwords and
        activates them.
      </p>
      <p>
        Operational JSON exports are not full backups. Back up the database for
        accounting, stock, manufacturing, expenses, attachments and audit
        recovery.
      </p>
      <div className="finance-actions">
        <button
          className="btn-secondary"
          disabled={busy}
          onClick={() => run("export")}
        >
          Export operational records
        </button>
        <button
          className="btn-secondary"
          disabled={busy}
          onClick={() => run("browser")}
        >
          Import this browser's old demo records
        </button>
      </div>
      <label>
        Select exported JSON (up to 10 MB)
        <input
          ref={file}
          type="file"
          accept="application/json,.json"
          disabled={busy}
        />
      </label>
      <button
        className="btn-primary"
        disabled={busy}
        onClick={() => run("file")}
      >
        Import selected file
      </button>
      {error && (
        <p role="alert" className="modern-error">
          {error}
        </p>
      )}
      {result && <p role="status">{result}</p>}
    </div>
  );
}
