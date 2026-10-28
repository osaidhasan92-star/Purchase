import { useEffect, useState } from "react";
import type { Bridge } from "../../types";
import { errorMessage } from "../../lib/api";
import {
  money,
  str,
  today,
  type PageData,
  type Summary,
  type Row,
} from "./types";
export function Pager({
  page,
  total,
  loading,
  onPage,
}: {
  page: number;
  total: number;
  loading: boolean;
  onPage: (p: number) => void;
}) {
  return (
    <div className="modern-pagination">
      <button disabled={loading || page === 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span>
        Page {page} · {total} records
      </span>
      <button
        disabled={loading || page * 25 >= total}
        onClick={() => onPage(page + 1)}
      >
        Next
      </button>
    </div>
  );
}
export function DataTable({
  columns,
  rows,
  onEntry,
}: {
  columns: [string, string, boolean?][];
  rows: Row[];
  onEntry?: (id: number) => void;
}) {
  return (
    <div className="finance-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map(([key, title]) => (
              <th key={key}>{title}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={str(r.id || r.code || i)}>
              {columns.map(([key, , amount]) => (
                <td key={key}>
                  {key === "entry" && onEntry ? (
                    <button
                      className="link-btn"
                      onClick={() => onEntry(Number(r.entryId))}
                    >
                      {str(r.entry)}
                    </button>
                  ) : amount ? (
                    money(r[key])
                  ) : (
                    str(r[key])
                  )}
                </td>
              ))}
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={columns.length}>No records found</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
export function SummaryCards({ summary }: { summary: Summary }) {
  return (
    <div className="stats">
      {[
        ["cashBank", "Cash & Bank"],
        ["receivables", "Receivables"],
        ["payables", "Payables"],
        ["profit", "Net Profit"],
      ].map(([key, title]) => (
        <div className="stat-card finance-stat" key={key}>
          <span>{title}</span>
          <strong>PKR {money(summary[key])}</strong>
        </div>
      ))}
    </div>
  );
}
export function FinanceReports({
  bridge,
  onEntry,
}: {
  bridge: Bridge;
  onEntry: (id: number) => void;
}) {
  const [kind, setKind] = useState("trial"),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(today()),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(1),
    [data, setData] = useState<PageData & { summary?: Summary }>({
      items: [],
      total: 0,
      page: 1,
      pageSize: 25,
    }),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0);
  const params = new URLSearchParams({
    from: start,
    to: end,
    search,
    page: String(page),
    pageSize: "25",
    kind,
  });
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const timer = setTimeout(() => {
      bridge
        .request<PageData & { summary?: Summary }>(
          "/finance/" +
            (kind === "ledger" ? "ledger" : "reports") +
            "?" +
            params,
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
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [bridge, kind, start, end, search, page, retry]);
  const columns: [string, string, boolean?][] =
    kind === "ledger"
      ? [
          ["date", "Date"],
          ["entry", "Entry"],
          ["account", "Account"],
          ["memo", "Memo"],
          ["partner", "Partner"],
          ["debit", "Debit PKR", true],
          ["credit", "Credit PKR", true],
        ]
      : kind === "pnl"
        ? [
            ["code", "Code"],
            ["name", "Account"],
            ["periodCredit", "Period credit PKR", true],
            ["periodDebit", "Period debit PKR", true],
          ]
        : [
            ["code", "Code"],
            ["name", "Account"],
            ["opening", "Opening net PKR", true],
            ["periodDebit", "Period debit PKR", true],
            ["periodCredit", "Period credit PKR", true],
            ["balance", "Closing net PKR", true],
          ];
  return (
    <section data-native-finance="reports" aria-busy={loading}>
      <div className="finance-filters">
        <label>
          Report
          <select
            aria-label="Report"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setPage(1);
            }}
          >
            <option value="trial">Trial Balance</option>
            <option value="ledger">General Ledger</option>
            <option value="pnl">Profit and Loss</option>
            <option value="balance">Balance Sheet</option>
            <option value="cash">Cash Movements</option>
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
        <label>
          Search report
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
        {kind === "ledger" && bridge.can("accounting", "export") && (
          <a
            className="btn-secondary"
            href={"/api/finance/ledger/export?" + params}
          >
            Export current page CSV
          </a>
        )}
      </div>
      {error && (
        <p className="modern-error" role="alert">
          {error}{" "}
          <button onClick={() => setRetry((v) => v + 1)}>Try again</button>
        </p>
      )}
      {loading ? (
        <p role="status">Loading financial report…</p>
      ) : (
        <>
          {data.summary && (
            <>
              <SummaryCards summary={data.summary} />
              {kind === "balance" && (
                <div className="finance-summary">
                  {[
                    ["assets", "Assets"],
                    ["liabilities", "Liabilities"],
                    ["equity", "Equity"],
                    ["currentEarnings", "Accumulated earnings"],
                    ["balanceCheck", "Balance check (must be zero)"],
                  ].map(([k, t]) => (
                    <p key={k}>
                      {t}: <strong>PKR {money(data.summary![k])}</strong>
                    </p>
                  ))}
                </div>
              )}
              {kind === "cash" && (
                <div className="finance-summary">
                  {[
                    ["openingCash", "Opening cash / bank"],
                    ["cashIn", "Cash / bank debits"],
                    ["cashOut", "Cash / bank credits"],
                    ["closingCash", "Closing cash / bank"],
                  ].map(([k, t]) => (
                    <p key={k}>
                      {t}: PKR {money(data.summary![k])}
                    </p>
                  ))}
                </div>
              )}
              <p>
                Company totals use all posted entries in the selected period;
                search filters the displayed rows. Closing balances and
                accumulated earnings are through the To date. Cash movements
                include internal transfers.
              </p>
            </>
          )}
          <DataTable columns={columns} rows={data.items} onEntry={onEntry} />
        </>
      )}
      <Pager
        page={page}
        total={data.total}
        loading={loading}
        onPage={setPage}
      />
    </section>
  );
}
