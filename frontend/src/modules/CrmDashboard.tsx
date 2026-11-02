import { useEffect, useState } from "react";
import type { Bridge } from "../types";
import { errorMessage } from "../lib/api";
import {
  Kpi,
  Panel,
  Trend,
  Funnel,
  DashboardLink,
  money,
} from "../components/dashboard/Dashboard";
interface Summary {
  active: number;
  foreignCurrencyLeads: number;
  pipeline: number;
  won: number;
  stages: { stage: string; count: number; value: number }[];
  due: {
    id: string | number;
    leadName: string;
    type: string;
    dueDate: string;
  }[];
  trend: { month: string; won: number; pipeline: number }[];
  leaders: { id: string | number; name: string; value: number }[];
  calendar: { date: string; count: number }[];
}
interface Activity {
  id: number;
  action: string;
  actor: string;
  at: string;
}
interface Quotes {
  registers: { key: string; count: number; statuses: Record<string, number> }[];
}
export function CrmDashboard({ bridge }: { bridge: Bridge }) {
  const [data, setData] = useState<Summary | null>(null),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0),
    [year, setYear] = useState("");
  const [quotes, setQuotes] = useState<Quotes | null>(null),
    [activities, setActivities] = useState<Activity[]>([]),
    [auxError, setAuxError] = useState("");
  const today = new Date(
      new Date().toLocaleString("en-US", { timeZone: "Asia/Karachi" }),
    ),
    currentYear = today.getFullYear();
  useEffect(() => {
    let active = true;
    setError("");
    setData(null);
    bridge
      .request<Summary>("/crm/summary" + (year ? "?year=" + year : ""))
      .then((r) => {
        if (active) setData(r);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [bridge, reload, year]);
  useEffect(() => {
    let active = true;
    setQuotes(null);
    setActivities([]);
    setAuxError("");
    const fetch = async () => {
      try {
        const q = bridge.can("sales_quotations")
          ? await bridge.request<Quotes>("/trade/summary/sales")
          : null;
        const a = bridge.can("activities")
          ? await bridge.request<{ items: Activity[] }>(
              "/administration/activities?pageSize=5",
            )
          : null;
        if (active) {
          setQuotes(q);
          setActivities(a?.items || []);
        }
      } catch (e) {
        if (active) setAuxError(errorMessage(e));
      }
    };
    void fetch();
    return () => {
      active = false;
    };
  }, [bridge, reload]);
  const won = data?.stages.find((r) => r.stage === "Closed Won")?.count || 0,
    lost = data?.stages.find((r) => r.stage === "Closed Lost")?.count || 0;
  const quote = quotes?.registers.find((r) => r.key === "salesQuotations");
  const month = today.getMonth(),
    first = new Date(currentYear, month, 1),
    days = new Date(currentYear, month + 1, 0).getDate();
  const iso = (d: number) =>
    `${currentYear}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  return (
    <section
      className="reference-dashboard crm-reference-dashboard"
      data-screen="crm-dashboard-react"
      aria-busy={!data && !error}
    >
      <div className="ref-toolbar">
        <label>
          <span className="sr-only">Lead closing year</span>
          <select
            aria-label="Lead closing year"
            value={year}
            onChange={(e) => setYear(e.target.value)}
          >
            <option value="">All Time</option>
            {[currentYear, currentYear - 1, currentYear - 2].map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <p className="modern-error" role="alert">
          {error}{" "}
          <button type="button" onClick={() => setReload((v) => v + 1)}>
            Try again
          </button>
        </p>
      )}
      {!data ? (
        <p aria-busy={!error}>Loading CRM…</p>
      ) : (
        <div aria-busy="false">
          <div className="ref-kpis crm-ref-kpis">
            <Kpi
              label="Total Sales"
              value={money(data.won)}
              hint="Closed won lead value"
              icon="cash"
            />
            <Kpi
              label="Forecast Revenue"
              value={money(data.pipeline)}
              hint="Open pipeline"
              tone="green"
              icon="chart"
            />
            <Kpi
              label="Open Leads"
              value={Math.max(0, data.active - won - lost)}
              hint="Active opportunities"
              tone="violet"
              icon="people"
            />
            <Kpi
              label="Conversion Rate"
              value={
                (data.active ? ((won / data.active) * 100).toFixed(1) : "0") +
                "%"
              }
              hint="Won / active lead records"
              tone="amber"
              icon="chart"
            />
          </div>
          {data.foreignCurrencyLeads > 0 && (
            <p className="hint">
              {data.foreignCurrencyLeads} legacy foreign-currency leads are
              excluded from PKR totals.
            </p>
          )}
          <Panel
            title="Revenue & Pipeline"
            subtitle={
              "Monthly opportunity value · expected close dates in " +
              (year || currentYear)
            }
            action={
              <span className="ref-chart-legend">
                <span>
                  <i />
                  Open pipeline
                </span>
                <span>
                  <i />
                  Closed won
                </span>
              </span>
            }
          >
            <Trend
              rows={data.trend.map((r) => ({
                month: r.month,
                value: r.pipeline,
                second: r.won,
              }))}
              secondary
              color="#08b78c"
              title="Monthly open pipeline and closed won lead value"
            />
          </Panel>
          <div className="ref-crm-grid">
            <Panel
              title="Leads Leaderboard"
              subtitle="By open opportunity value"
            >
              <div className="ref-leaders">
                {data.leaders.length ? (
                  data.leaders.map((r, i) => (
                    <a
                      href={
                        "erp.html?view=leads&module=crm&search=" +
                        encodeURIComponent(r.name)
                      }
                      key={r.id}
                    >
                      <span className="ref-rank">{i + 1}</span>
                      <span className="ref-avatar">
                        {r.name
                          .split(/\s+/)
                          .map((w) => w[0])
                          .slice(0, 2)
                          .join("")}
                      </span>
                      <div>
                        <div className="ref-leader-label">
                          <b>{r.name}</b>
                          <span>{money(r.value)}</span>
                        </div>
                        <div className="ref-track">
                          <span
                            style={{
                              width:
                                (r.value / Math.max(1, data.leaders[0].value)) *
                                  100 +
                                "%",
                            }}
                          />
                        </div>
                      </div>
                    </a>
                  ))
                ) : (
                  <p className="ref-empty">No open leads yet.</p>
                )}
              </div>
            </Panel>
            <Panel title="Pipeline by Stage" subtitle="Active opportunities">
              <Funnel
                rows={data.stages.map((r) => ({
                  label: r.stage,
                  count: r.count,
                }))}
              />
              {!data.stages.length && (
                <p className="ref-empty">No leads yet.</p>
              )}
            </Panel>
          </div>
          <Panel
            title={today.toLocaleDateString("en-GB", {
              month: "long",
              year: "numeric",
            })}
            subtitle="Follow-up calendar"
            action={
              bridge.can("reminders") ? (
                <DashboardLink href="erp.html?view=reminders&module=crm">
                  View reminders
                </DashboardLink>
              ) : undefined
            }
          >
            <div className="ref-calendar-row">
              <div
                className="ref-calendar"
                aria-label="Current month follow-up calendar"
              >
                <div className="ref-weekdays">
                  {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(
                    (d) => (
                      <span key={d}>{d}</span>
                    ),
                  )}
                </div>
                <div className="ref-calendar-days">
                  {Array.from({ length: first.getDay() }, (_, i) => (
                    <span key={"empty" + i} />
                  ))}
                  {Array.from({ length: days }, (_, i) => {
                    const day = i + 1,
                      n =
                        data.calendar.find((r) => r.date === iso(day))?.count ||
                        0;
                    return (
                      <div
                        key={day}
                        className={day === today.getDate() ? "is-today" : ""}
                      >
                        <span>{day}</span>
                        {n > 0 && (
                          <a
                            href={"erp.html?view=reminders&module=crm"}
                            aria-label={n + " follow-ups on " + iso(day)}
                          >
                            {n} due
                          </a>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
              <aside className="ref-quote-summary">
                <h4>Quote Summary</h4>
                <p>Commercial progress</p>
                {quote ? (
                  [
                    ["Total quotes", quote.count],
                    ["Sent", quote.statuses.Sent || 0],
                    ["Accepted", quote.statuses.Accepted || 0],
                    [
                      "Open / pending",
                      Object.entries(quote.statuses)
                        .filter(
                          ([s]) =>
                            !["Accepted", "Rejected", "Cancelled"].includes(s),
                        )
                        .reduce((n, [, v]) => n + v, 0),
                    ],
                  ].map(([label, n]) => (
                    <div key={label}>
                      <span>{label}</span>
                      <b>{n}</b>
                    </div>
                  ))
                ) : (
                  <p>
                    {bridge.can("sales_quotations")
                      ? "Quotation summary unavailable."
                      : "Quotation access is restricted."}
                  </p>
                )}
              </aside>
            </div>
          </Panel>
          <div className="ref-crm-grid">
            <Panel
              title="Due Follow-ups"
              subtitle="Open reminders due today or earlier"
            >
              {data.due.length ? (
                <div className="ref-recent">
                  {data.due.map((r) => (
                    <a key={r.id} href="erp.html?view=reminders&module=crm">
                      <div>
                        <b>{r.leadName}</b>
                        <small>{r.type}</small>
                      </div>
                      <small>{r.dueDate}</small>
                    </a>
                  ))}
                </div>
              ) : (
                <p className="ref-empty">No follow-ups due</p>
              )}
            </Panel>
            <Panel
              title="Activity Log"
              subtitle="Latest authorized system activity"
            >
              {auxError && (
                <p role="alert" className="modern-error">
                  {auxError}
                </p>
              )}
              {activities.length ? (
                <div className="ref-activities">
                  {activities.map((a) => (
                    <div key={a.id}>
                      <i />
                      <div>
                        <b>{a.action}</b>
                        <small>
                          {a.actor} ·{" "}
                          {new Date(a.at).toLocaleDateString("en-GB")}
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="ref-empty">
                  {bridge.can("activities")
                    ? "No recent activity."
                    : "Activity access is restricted."}
                </p>
              )}
            </Panel>
          </div>
        </div>
      )}
    </section>
  );
}
