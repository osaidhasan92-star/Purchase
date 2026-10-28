import { useEffect, useRef, useState } from "react";
import type { Bridge } from "../../types";
import { Dialog } from "../../components/Dialog";
import { Pager } from "../finance/FinanceReports";
import {
  money,
  today,
  requestKey,
  type PageData,
  type Row,
} from "../finance/types";
import { errorMessage } from "../../lib/api";
interface Claim extends Row {
  id: number;
  number: string;
  employee: string;
  description: string;
  account: string;
  amount: string;
  tax: string;
  total: string;
  date: string;
  status: string;
  attachmentId: string | null;
  version: string;
  actions: string[];
}
interface Summary {
  states: Record<string, number>;
  amounts: Record<string, string>;
}
export function ExpensePage({
  view,
  bridge,
}: {
  view: "expenses" | "expense-claims";
  bridge: Bridge;
}) {
  const [data, setData] = useState<PageData>({
      items: [],
      total: 0,
      page: 1,
      pageSize: 25,
    }),
    [summary, setSummary] = useState<Summary | null>(null),
    [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState(""),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [reload, setReload] = useState(0),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [claim, setClaim] = useState<Claim | null>(null),
    [form, setForm] = useState<"create" | "pay" | null>(null);
  const lock = useRef(false),
    keys = useRef(new Map<string, string>());
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(
      () =>
        Promise.all([
          bridge.request<Summary>("/expenses/summary"),
          view === "expenses"
            ? Promise.resolve(null)
            : bridge.request<PageData>(
                "/expenses/claims?" +
                  new URLSearchParams({
                    page: String(page),
                    pageSize: "25",
                    search,
                    status,
                    from: start,
                    to: end,
                  }),
              ),
        ])
          .then(([s, d]) => {
            if (active) {
              setSummary(s);
              if (d) setData(d);
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
  }, [bridge, view, page, search, status, start, end, reload]);
  useEffect(() => {
    const id = new URLSearchParams(location.search).get("id");
    if (id) void open(Number(id));
  }, []);
  async function open(id: number) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      setClaim(
        (await bridge.request<{ record: Claim }>("/expenses/claims/" + id))
          .record,
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function action(kind: string, extra: Record<string, unknown> = {}) {
    if (!claim || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    const signature = JSON.stringify([kind, claim.id, extra]);
    if (!keys.current.has(signature)) keys.current.set(signature, requestKey());
    try {
      const r = await bridge.request<{ record: Claim }>(
        "/expenses/commands/" + kind,
        {
          method: "POST",
          body: JSON.stringify({
            id: claim.id,
            version: claim.version,
            ...extra,
            requestKey: keys.current.get(signature),
          }),
        },
      );
      setClaim(r.record);
      setForm(null);
      setReload((n) => n + 1);
      bridge.toast("Expense " + r.record.status.toLowerCase());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  function created(c: Claim) {
    setForm(null);
    setClaim(c);
    setReload((n) => n + 1);
  }
  return (
    <section
      className="finance-workspace"
      data-native-expenses
      aria-busy={loading}
    >
      <div className="section-head">
        <div>
          <h2>
            {view === "expenses"
              ? "Expense overview"
              : "Expense claim register"}
          </h2>
          <p>
            {view === "expenses"
              ? "Submit → approve → reimburse"
              : "Claims visible to you and your authorized team"}
          </p>
        </div>
        {bridge.can("expenses", "create") && (
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() => {
              setError("");
              setForm("create");
            }}
          >
            New Expense
          </button>
        )}
      </div>
      {error && (
        <div role="alert" className="modern-error">
          {error}
        </div>
      )}
      {view === "expenses" ? (
        <>
          <div className="stats">
            {["Draft", "Submitted", "Approved", "Paid", "Rejected"].map((s) => (
              <div className="stat-card finance-stat" key={s}>
                <span>{s}</span>
                <strong>{summary?.states[s] || 0}</strong>
                <p>PKR {money(summary?.amounts[s])}</p>
              </div>
            ))}
          </div>
          <div className="erp-grid">
            <a className="erp-module" href="erp.html?view=expense-claims">
              <h3>Expense Claims</h3>
              <p>
                Open claims, inspect receipts, and complete authorized approvals
                and reimbursements.
              </p>
            </a>
            <div className="erp-module">
              <h3>Automatic accounting</h3>
              <p>
                Approval records the expense and employee payable. Reimbursement
                clears the payable against bank or cash.
              </p>
            </div>
            <div className="erp-module">
              <h3>Your claim totals</h3>
              <p>
                Totals reflect only claims you can access. Tax is entered
                manually. Drafts do not post to the ledger.
              </p>
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="finance-filters">
            <label>
              Search
              <input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Number, employee or description"
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
                {["Draft", "Submitted", "Approved", "Paid", "Rejected"].map(
                  (s) => (
                    <option key={s}>{s}</option>
                  ),
                )}
              </select>
            </label>
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
          </div>
          <div className="finance-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {[
                    "Claim",
                    "Employee",
                    "Description",
                    "Date",
                    "Total PKR",
                    "Status",
                  ].map((s) => (
                    <th key={s}>{s}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <button
                        className="link-btn"
                        disabled={busy}
                        onClick={() => open(Number(r.id))}
                      >
                        {String(r.number)}
                      </button>
                    </td>
                    {["employee", "description", "date"].map((k) => (
                      <td key={k}>{String(r[k])}</td>
                    ))}
                    <td>{money(r.total)}</td>
                    <td>{String(r.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && !data.items.length && <p>No expense claims found.</p>}
          </div>
          <Pager
            page={page}
            total={data.total}
            loading={loading}
            onPage={setPage}
          />
        </>
      )}
      {claim && !form && (
        <Dialog title={claim.number} busy={busy} onClose={() => setClaim(null)}>
          <div className="modal-body">
            {error && (
              <p role="alert" className="modern-error">
                {error}
              </p>
            )}
            <dl>
              {[
                ["Employee", claim.employee],
                ["Description", claim.description],
                ["Date", claim.date],
                ["Status", claim.status],
                ["Expense account", claim.account],
                ["Amount PKR", money(claim.amount)],
                ["Tax PKR", money(claim.tax)],
                ["Total PKR", money(claim.total)],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
            {claim.attachmentId && (
              <a
                href={
                  "/api/attachments/" + encodeURIComponent(claim.attachmentId)
                }
                target="_blank"
                rel="noreferrer"
              >
                Open PDF receipt
              </a>
            )}
            {bridge.can("accounting") &&
              ["Approved", "Paid"].includes(claim.status) && (
                <p>
                  <a
                    href={
                      "erp.html?view=journals&source=" +
                      encodeURIComponent("expense:" + claim.id)
                    }
                  >
                    Approval journal
                  </a>
                  {claim.status === "Paid" && (
                    <>
                      {" "}
                      ·{" "}
                      <a
                        href={
                          "erp.html?view=journals&source=" +
                          encodeURIComponent("expense:" + claim.id + ":payment")
                        }
                      >
                        Reimbursement journal
                      </a>
                    </>
                  )}
                </p>
              )}
            {bridge.can("expenses", "export") && (
              <p>
                <a
                  href={"/api/expenses/claims/" + claim.id + "/print"}
                  target="_blank"
                  rel="noreferrer"
                >
                  Print / Save as PDF
                </a>
              </p>
            )}
          </div>
          <div className="modal-foot">
            {claim.actions.map((a) => (
              <button
                key={a}
                className="btn"
                disabled={busy}
                onClick={() => (a === "pay" ? setForm("pay") : action(a))}
              >
                {
                  {
                    submit: "Submit",
                    approve: "Approve",
                    reject: "Reject",
                    pay: "Reimburse",
                  }[a]
                }
              </button>
            ))}
            <button
              className="btn"
              disabled={busy}
              onClick={() => open(claim.id)}
            >
              Reload Claim
            </button>
          </div>
        </Dialog>
      )}
      {form === "create" && (
        <ExpenseForm
          bridge={bridge}
          onClose={() => setForm(null)}
          onSaved={created}
        />
      )}
      {form === "pay" && claim && (
        <Dialog
          title={"Reimburse " + claim.number}
          busy={busy}
          onClose={() => setForm(null)}
        >
          <form
            className="trade-form expense-form"
            onSubmit={(e) => {
              e.preventDefault();
              const d = new FormData(e.currentTarget);
              void action("pay", {
                account: d.get("account"),
                date: d.get("date"),
              });
            }}
          >
            <div className="expense-form-body">
              <p>
                PKR {money(claim.total)} payable to {claim.employee}
              </p>
              <label>
                Payment account
                <select name="account" aria-label="Payment account">
                  <option value="1010">Bank</option>
                  <option value="1000">Cash</option>
                </select>
              </label>
              <label>
                Payment date
                <input
                  required
                  type="date"
                  name="date"
                  defaultValue={today()}
                />
              </label>
              {error && <p role="alert">{error}</p>}
            </div>
            <div className="modal-foot">
              <button className="btn btn-primary" disabled={busy}>
                Confirm Reimbursement
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </section>
  );
}
function ExpenseForm({
  bridge,
  onClose,
  onSaved,
}: {
  bridge: Bridge;
  onClose: () => void;
  onSaved: (c: Claim) => void;
}) {
  const [accounts, setAccounts] = useState<{ id: string; name: string }[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const locked = useRef(false),
    key = useRef(requestKey()),
    receipt = useRef<{ file: File; id: string } | null>(null),
    signature = useRef("");
  useEffect(() => {
    let active = true;
    bridge
      .request<{ items: { id: string; name: string }[] }>(
        "/expenses/accounts?pageSize=100",
      )
      .then((r) => {
        if (active) setAccounts(r.items);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [bridge]);
  async function save(form: HTMLFormElement) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      const d = new FormData(form),
        file = d.get("receipt") as File;
      let attachmentId: string | null = null;
      if (file?.size) {
        if (file.size > 10 * 1024 * 1024)
          throw new Error("Upload a PDF of at most 10 MB");
        if (receipt.current?.file === file) attachmentId = receipt.current.id;
        else {
          const upload = new FormData();
          upload.set("module", "expenses");
          upload.set("file", file);
          const r = await bridge.request<{ attachmentPath: string }>(
            "/attachments",
            { method: "POST", body: upload },
          );
          attachmentId = r.attachmentPath;
          receipt.current = { file, id: attachmentId };
        }
      }
      const values = {
        description: d.get("description"),
        account: d.get("account"),
        amount: d.get("amount"),
        tax: d.get("tax"),
        date: d.get("date"),
        attachmentId,
      };
      const next = JSON.stringify(values);
      if (signature.current && signature.current !== next)
        key.current = requestKey();
      signature.current = next;
      const r = await bridge.request<{ record: Claim }>(
        "/expenses/commands/create",
        {
          method: "POST",
          body: JSON.stringify({ ...values, requestKey: key.current }),
        },
      );
      onSaved(r.record);
      bridge.toast("Expense created");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <Dialog title="New Expense" busy={busy} onClose={onClose}>
      <form
        className="trade-form expense-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save(e.currentTarget);
        }}
      >
        <div className="expense-form-body">
          <p>The signed-in user is recorded as the claimant.</p>
          {error && (
            <p role="alert" className="modern-error">
              {error}
            </p>
          )}
          <label>
            Description
            <textarea name="description" required maxLength={500} />
          </label>
          <div className="form-grid">
            <label>
              Expense date
              <input name="date" type="date" required defaultValue={today()} />
            </label>
            <label>
              Expense account
              <select
                key={accounts.length}
                aria-label="Expense account"
                name="account"
                required
                defaultValue="6105"
              >
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.id} · {a.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Amount PKR
              <input
                name="amount"
                type="number"
                required
                min="0.01"
                step="0.01"
              />
            </label>
            <label>
              Tax PKR
              <input
                name="tax"
                type="number"
                required
                min="0"
                step="0.01"
                defaultValue="0"
              />
            </label>
          </div>
          <label>
            Receipt (PDF, up to 10 MB)
            <input name="receipt" type="file" accept="application/pdf,.pdf" />
          </label>
          <p>
            Draft claims do not post to the ledger. Rejected claims are
            terminal; create a new claim to resubmit.
          </p>
        </div>
        <div className="modal-foot">
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={busy || !accounts.length}
          >
            Save Expense
          </button>
        </div>
      </form>
    </Dialog>
  );
}
