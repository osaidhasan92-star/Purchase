import { useEffect, useState } from "react";
import type { Bridge } from "../types";
import { errorMessage } from "../lib/api";
interface Summary {
  active: number;
  pipeline: number;
  won: number;
  stages: { stage: string; count: number; value: number }[];
  due: {
    id: string | number;
    leadName: string;
    type: string;
    dueDate: string;
  }[];
}
export function CrmDashboard({ bridge }: { bridge: Bridge }) {
  const [data, setData] = useState<Summary | null>(null),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    bridge
      .request<Summary>("/crm/summary")
      .then((result) => {
        if (active) setData(result);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [bridge, reload]);
  const money = (value: number) =>
    "Rs " +
    value.toLocaleString("en-PK", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  return (
    <div data-screen="crm-dashboard-react">
      {error && (
        <p className="modern-error" role="alert">
          {error}{" "}
          <button type="button" onClick={() => setReload((v) => v + 1)}>
            Try again
          </button>
        </p>
      )}
      {!data ? (
        <p aria-busy="true">Loading CRM…</p>
      ) : (
        <>
          <div className="stats">
            {[
              ["Active Leads", data.active],
              ["Open Pipeline", money(data.pipeline)],
              ["Won Value", money(data.won)],
            ].map(([label, value]) => (
              <div className="stat-card" key={label}>
                <span>{label}</span>
                <h2>{value}</h2>
              </div>
            ))}
          </div>
          <div className="grid2">
            <section className="section-card">
              <div className="section-head">
                <h3>Pipeline by Stage</h3>
                <a
                  className="btn-secondary"
                  href="erp.html?view=leads&module=crm"
                >
                  View leads
                </a>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Stage</th>
                      <th>Leads</th>
                      <th>Value (PKR)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.stages.map((row) => (
                      <tr key={row.stage}>
                        <td>{row.stage}</td>
                        <td>{row.count}</td>
                        <td>{money(row.value)}</td>
                      </tr>
                    ))}
                    {!data.stages.length && (
                      <tr>
                        <td colSpan={3}>No leads yet</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="section-card">
              <div className="section-head">
                <h3>Due Follow-ups</h3>
                {bridge.can("reminders") && (
                  <a
                    className="btn-secondary"
                    href="erp.html?view=reminders&module=crm"
                  >
                    View reminders
                  </a>
                )}
              </div>
              <p className="hint">
                Up to 25 open reminders due today or earlier
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Lead</th>
                      <th>Type</th>
                      <th>Due</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.due.map((row) => (
                      <tr key={row.id}>
                        <td>{row.leadName}</td>
                        <td>{row.type}</td>
                        <td>{row.dueDate}</td>
                      </tr>
                    ))}
                    {!data.due.length && (
                      <tr>
                        <td colSpan={3}>No follow-ups due</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
