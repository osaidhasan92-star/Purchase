import { useEffect, useRef, useState } from "react";
import type { Bridge, User } from "../../types";
import { Dialog } from "../../components/Dialog";
import { errorMessage } from "../../lib/api";
import { FinanceForm, type FormState } from "./FinanceForms";
import {
  FinanceReports,
  Pager,
  DataTable,
  SummaryCards,
} from "./FinanceReports";
import {
  money,
  str,
  titles,
  requestKey,
  type FinanceView,
  type Journal,
  type PageData,
  type Row,
  type Summary,
} from "./types";
export function FinancePage({
  view,
  bridge,
  user,
}: {
  view: FinanceView;
  bridge: Bridge;
  user: User;
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
    [from, setFrom] = useState(""),
    [to, setTo] = useState(""),
    [source, setSource] = useState(
      () => new URLSearchParams(location.search).get("source") || "",
    ),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0),
    [form, setForm] = useState<FormState | null>(null),
    [detail, setDetail] = useState<Journal | null>(null),
    [busy, setBusy] = useState(false);
  const locked = useRef(false),
    keys = useRef(new Map<string, string>());
  useEffect(() => {
    if (view === "reports") {
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(() => {
      const path =
        view === "accounting"
          ? "/finance/summary"
          : "/finance/" +
            {
              accounts: "accounts",
              journals: "entries",
              aged: "open-items",
              bank: "statements",
            }[view] +
            "?" +
            new URLSearchParams({
              page: String(page),
              pageSize: "25",
              search,
              status,
              from,
              to,
              source,
            });
      bridge
        .request<Summary | PageData>(path)
        .then((r) => {
          if (active) {
            if (view === "accounting") setSummary(r as Summary);
            else setData(r as PageData);
          }
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
  }, [bridge, view, page, search, status, from, to, source, reload]);
  async function openEntry(id: number) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      setDetail(
        (await bridge.request<{ record: Journal }>("/finance/entries/" + id))
          .record,
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  async function post() {
    if (!detail || locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    const slot = detail.id + ":" + detail.version;
    if (!keys.current.has(slot)) keys.current.set(slot, requestKey());
    try {
      const r = await bridge.request<{ record: Journal }>(
        "/finance/commands/post",
        {
          method: "POST",
          body: JSON.stringify({
            id: detail.id,
            version: detail.version,
            requestKey: keys.current.get(slot),
          }),
        },
      );
      setDetail(r.record);
      setReload((v) => v + 1);
      bridge.toast("Journal posted");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  const create = bridge.can("accounting", "create"),
    approve = bridge.can("accounting", "approve");
  const add = (kind: FormState["kind"], record?: Row | Journal) => {
    setDetail(null);
    setForm({ kind, record });
  };
  const columns: [string, string, boolean?][] =
    view === "accounts"
      ? [
          ["code", "Code"],
          ["accountName", "Account"],
          ["type", "Type"],
          ["reconcile", "Reconciliation"],
        ]
      : view === "aged"
        ? [
            ["id", "Journal item"],
            ["entry", "Entry"],
            ["account", "Account"],
            ["partner", "Partner"],
            ["dueDate", "Due"],
            ["bucket", "Aging"],
            ["debit", "Debit PKR", true],
            ["credit", "Credit PKR", true],
            ["openAmount", "Open PKR", true],
          ]
        : [];
  return (
    <section
      className="finance-workspace"
      data-native-finance={view}
      aria-busy={loading}
    >
      <div className="section-head">
        <div>
          <h2>{view === "accounting" ? "Financial position" : titles[view]}</h2>
          <p>Pakistan · PKR · Posted journals drive financial balances.</p>
        </div>
        <div className="finance-actions">
          {view === "accounts" && create && (
            <button className="btn-primary" onClick={() => add("account")}>
              New Account
            </button>
          )}
          {view === "journals" && create && (
            <button className="btn-primary" onClick={() => add("journal")}>
              New Journal Entry
            </button>
          )}
          {view === "bank" && create && (
            <button className="btn-primary" onClick={() => add("statement")}>
              New Statement Line
            </button>
          )}
          {view === "aged" && approve && (
            <button className="btn-primary" onClick={() => add("reconcile")}>
              Match Open Items
            </button>
          )}
          {view === "accounting" && (
            <>
              {create && approve && (
                <button className="btn-primary" onClick={() => add("transfer")}>
                  Bank / Cash Transfer
                </button>
              )}
              {user.role === "Admin" && summary && (
                <button
                  className="btn-secondary"
                  onClick={() =>
                    add("period-lock", summary.periodLock as unknown as Row)
                  }
                >
                  Period Lock
                </button>
              )}
            </>
          )}
        </div>
      </div>
      {error && (
        <p className="modern-error" role="alert">
          {error}{" "}
          <button onClick={() => setReload((v) => v + 1)}>Try again</button>
        </p>
      )}
      {view !== "accounting" && view !== "reports" && (
        <div className="finance-filters">
          <label>
            Search
            <input
              type="search"
              value={search}
              maxLength={160}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </label>
          {(view === "bank" || view === "journals") && (
            <label>
              Status
              <select
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All statuses</option>
                {(view === "bank"
                  ? ["Unmatched", "Matched"]
                  : ["Draft", "Posted"]
                ).map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
          )}
          {view === "journals" && (
            <>
              <label>
                From
                <input
                  type="date"
                  value={from}
                  onChange={(e) => {
                    setFrom(e.target.value);
                    setPage(1);
                  }}
                />
              </label>
              <label>
                To
                <input
                  type="date"
                  value={to}
                  onChange={(e) => {
                    setTo(e.target.value);
                    setPage(1);
                  }}
                />
              </label>
              {source && (
                <p>
                  Source: {source}{" "}
                  <button
                    onClick={() => {
                      setSource("");
                      setPage(1);
                    }}
                  >
                    Clear source filter
                  </button>
                </p>
              )}
            </>
          )}
        </div>
      )}
      {view === "reports" ? (
        <FinanceReports bridge={bridge} onEntry={(id) => void openEntry(id)} />
      ) : loading ? (
        <p role="status">Loading accounting records…</p>
      ) : view === "accounting" && summary ? (
        <>
          <SummaryCards summary={summary} />
          <div className="erp-grid">
            {[
              [
                "journals",
                "Journal Entries",
                "Review automatic postings or prepare balanced manual journals.",
              ],
              [
                "accounts",
                "Chart of Accounts",
                "Review and add company accounts.",
              ],
              [
                "reports",
                "Financial Reports",
                "Trial balance, general ledger, statements and cash movements.",
              ],
              [
                "aged",
                "Receivables & Payables",
                "Current open invoices and payments; partial matching.",
              ],
              [
                "bank",
                "Bank Reconciliation",
                "Match statement lines to posted bank or cash items.",
              ],
            ].map(([v, t, d]) => (
              <a className="erp-module" key={v} href={"erp.html?view=" + v}>
                <h3>{t}</h3>
                <p>{d}</p>
              </a>
            ))}
          </div>
          <p>
            Accounting locked through: {str(summary.periodLock.date)}. Balance
            check: PKR {money(summary.balanceCheck)}.
          </p>
        </>
      ) : (
        <>
          {(view === "accounts" || view === "aged") && (
            <DataTable
              rows={data.items}
              columns={columns}
              onEntry={(id) => void openEntry(id)}
            />
          )}{" "}
          {view === "journals" && (
            <div className="finance-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {[
                      "Entry",
                      "Date",
                      "Memo / source",
                      "Debit PKR",
                      "Credit PKR",
                      "Status",
                      "Actions",
                    ].map((t) => (
                      <th key={t}>{t}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={str(r.id)}>
                      <td>{str(r.number)}</td>
                      <td>{str(r.date)}</td>
                      <td>
                        {str(r.memo)}
                        <small className="finance-source">
                          {str(r.source)}
                        </small>
                      </td>
                      <td>{money(r.debit)}</td>
                      <td>{money(r.credit)}</td>
                      <td>{str(r.status)}</td>
                      <td>
                        <button
                          className="btn-secondary btn-sm"
                          onClick={() => void openEntry(Number(r.id))}
                          disabled={busy}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!data.items.length && (
                    <tr>
                      <td colSpan={7}>No journal entries found</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          {view === "bank" && (
            <div className="finance-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {[
                      "Date",
                      "Description",
                      "Account",
                      "Signed amount PKR",
                      "Status",
                      "Actions",
                    ].map((t) => (
                      <th key={t}>{t}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={str(r.id)}>
                      <td>{str(r.date)}</td>
                      <td>{str(r.description)}</td>
                      <td>{str(r.account)}</td>
                      <td>{money(r.amount)}</td>
                      <td>{r.matchedLine ? "Matched" : "Unmatched"}</td>
                      <td>
                        {!r.matchedLine && approve ? (
                          <button
                            className="btn-secondary btn-sm"
                            onClick={() => add("match-bank", r)}
                          >
                            Match
                          </button>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                  {!data.items.length && (
                    <tr>
                      <td colSpan={6}>No statement lines found</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          {view === "aged" && (
            <p>
              Aging uses current reconciliation state, not historical settlement
              balances. Click an entry to inspect journal items.
            </p>
          )}
          <Pager
            page={page}
            total={data.total}
            loading={loading}
            onPage={setPage}
          />
        </>
      )}
      {form && (
        <FinanceForm
          form={form}
          bridge={bridge}
          onClose={() => setForm(null)}
          onSaved={(record) => {
            setForm(null);
            setReload((v) => v + 1);
            if (
              (form.kind === "journal" ||
                form.kind === "edit-journal" ||
                form.kind === "reverse" ||
                form.kind === "transfer") &&
              record.lines
            )
              setDetail(record as Journal);
          }}
        />
      )}
      {detail && (
        <Dialog
          title={"Journal " + detail.number}
          busy={busy}
          onClose={() => setDetail(null)}
        >
          <div className="modal-body">
            <p>
              {detail.date} · {detail.memo} · {detail.status}
            </p>
            <p className="finance-source">Source: {detail.source}</p>
            {detail.sourceLink && (
              <p>
                <a
                  className="btn-secondary"
                  href={detail.sourceLink.href}
                  target="_blank"
                  rel="noopener"
                >
                  {detail.sourceLink.label}
                </a>
              </p>
            )}
            <DataTable
              columns={[
                ["account", "Account"],
                ["partner", "Partner"],
                ["dueDate", "Due"],
                ["debit", "Debit PKR", true],
                ["credit", "Credit PKR", true],
                ["openAmount", "Open PKR", true],
              ]}
              rows={detail.lines.map((l, i) => ({ ...l, id: l.id || i }))}
            />
            {!!detail.reversedBy && (
              <p>Reversed by journal ID {str(detail.reversedBy)}</p>
            )}
            {error && (
              <p role="alert" className="modern-error">
                {error}
              </p>
            )}
          </div>
          <div className="modal-foot">
            {detail.actions.includes("edit") && (
              <button
                disabled={busy}
                onClick={() => add("edit-journal", detail)}
              >
                Edit Draft
              </button>
            )}
            {detail.actions.includes("post") && (
              <button
                disabled={busy}
                className="btn-primary"
                onClick={() => void post()}
              >
                Post Journal
              </button>
            )}
            {detail.actions.includes("reverse") && (
              <button disabled={busy} onClick={() => add("reverse", detail)}>
                Reverse Journal
              </button>
            )}
            {bridge.can("accounting", "export") && (
              <a
                className="btn-secondary"
                target="_blank"
                rel="noopener"
                href={"/api/finance/entries/" + detail.id + "/print"}
              >
                Print / Save as PDF
              </a>
            )}
            <button disabled={busy} onClick={() => setDetail(null)}>
              Close
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
