import { useEffect, useState } from "react";
import type { Bridge, User } from "../../types";
import { Dialog } from "../../components/Dialog";
import { errorMessage } from "../../lib/api";
import { money } from "../finance/types";
import { Pager } from "../finance/FinanceReports";
interface Approval {
  id: number;
  label: string;
  module: string;
  amount: string;
  requester: string;
  assignedTo: string | null;
  status: string;
  reason: string | null;
  version: string;
  canDecide: boolean;
  details: Record<string, unknown>;
}
interface Policy {
  limits: Record<string, string>;
  roles: string[];
  version: string;
  enabled: boolean;
}
function ReviewValues({ value }: { value: Record<string, unknown> }) {
  return (
    <dl className="detail-grid">
      {Object.entries(value).map(([key, entry]) => (
        <div key={key}>
          <dt>
            {key
              .replace(/([A-Z])/g, " $1")
              .replace(/^./, (s) => s.toUpperCase())}
          </dt>
          <dd>
            {Array.isArray(entry) ? (
              entry.map((line, i) => (
                <div key={i}>
                  <strong>Line {i + 1}</strong>
                  {line && typeof line === "object" ? (
                    <ReviewValues value={line as Record<string, unknown>} />
                  ) : (
                    String(line)
                  )}
                </div>
              ))
            ) : entry && typeof entry === "object" ? (
              <ReviewValues value={entry as Record<string, unknown>} />
            ) : key === "attachmentHref" &&
              typeof entry === "string" &&
              entry.startsWith("/api/attachments/") ? (
              <a href={entry} target="_blank" rel="noopener">
                View supporting receipt
              </a>
            ) : (
              String(entry ?? "—")
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function ApprovalsPage({
  bridge,
  user,
}: {
  bridge: Bridge;
  user: User;
}) {
  const submitted = new URLSearchParams(location.search).get("submitted");
  const [items, setItems] = useState<Approval[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(1),
    [status, setStatus] = useState(submitted ? "" : "Pending"),
    [reload, setReload] = useState(0),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [selected, setSelected] = useState<Approval | null>(null),
    [decision, setDecision] = useState<"approve" | "reject" | null>(null),
    [reason, setReason] = useState(""),
    [controls, setControls] = useState(false),
    [policy, setPolicy] = useState<Policy | null>(null),
    [limits, setLimits] = useState<Record<string, string>>({}),
    [changeReason, setChangeReason] = useState("");
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    bridge
      .request("/approvals/refresh", { method: "POST", body: "{}" })
      .then(() =>
        bridge.request<{ items: Approval[]; total: number }>(
          "/approvals/requests?" +
            new URLSearchParams({
              page: String(page),
              pageSize: "25",
              status,
              ...(submitted ? { id: submitted } : {}),
            }),
        ),
      )
      .then((result) => {
        if (active) {
          setItems(result.items);
          setTotal(result.total);
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
  }, [bridge, page, status, reload, submitted]);
  async function openControls() {
    setBusy(true);
    setError("");
    try {
      const result = await bridge.request<Policy>("/approvals/policy");
      setPolicy(result);
      setLimits(result.limits);
      setControls(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function decide() {
    if (!selected || !decision || busy) return;
    setBusy(true);
    setError("");
    try {
      await bridge.request(
        "/approvals/requests/" + selected.id + "/" + decision,
        {
          method: "POST",
          body: JSON.stringify({ version: selected.version, reason }),
        },
      );
      setSelected(null);
      setDecision(null);
      setReason("");
      setReload((v) => v + 1);
      bridge.toast(
        decision === "approve" ? "Approved and executed" : "Request rejected",
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function savePolicy() {
    if (!policy || busy) return;
    setBusy(true);
    setError("");
    try {
      await bridge.request("/approvals/policy", {
        method: "POST",
        body: JSON.stringify({
          version: policy.version,
          limits,
          reason: changeReason,
        }),
      });
      setControls(false);
      setReload((v) => v + 1);
      setChangeReason("");
      bridge.toast("Approval limits updated");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="section-card"
      data-native-approvals
      data-native-admin="approvals"
      aria-busy={loading}
    >
      <div className="section-head">
        <div>
          <h2>Pending Approvals</h2>
          <p>Independent review · PKR limits · Recorded decisions</p>
        </div>
        <div className="finance-actions">
          <button
            className="btn-primary"
            disabled={busy || loading}
            onClick={() => setReload((v) => v + 1)}
          >
            Check for requests
          </button>
          {user.role === "Admin" && (
            <button
              className="btn-secondary"
              disabled={busy}
              onClick={() => void openControls()}
            >
              Approval Controls
            </button>
          )}
        </div>
      </div>
      {submitted && (
        <p role="status" className="detail-note">
          Your request is recorded below. It requires an independent approver
          before any business changes post.
        </p>
      )}
      <p className="hint">
        Your submitted requests and assigned reviews appear here. Limits start
        unconfigured; Admin must set role limits and provide another eligible
        approver. Existing module and team permissions still apply. Discovery
        checks up to 100 new documents per register per refresh.
      </p>
      {error && !selected && !controls && (
        <p role="alert" className="modern-error">
          {error}
        </p>
      )}
      <div className="finance-filters">
        <label>
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="Pending">Pending</option>
            <option value="Approved">Approved</option>
            <option value="Rejected">Rejected</option>
            <option value="">All</option>
          </select>
        </label>
      </div>
      <div className="finance-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {[
                "Request",
                "Requester / creator",
                "Assigned approver",
                "Amount PKR",
                "Status",
                "Actions",
              ].map((v) => (
                <th key={v}>{v}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{row.label}</td>
                <td>{row.requester}</td>
                <td>
                  {row.assignedTo ||
                    "No eligible approver — review limits and accounts"}
                </td>
                <td>{money(row.amount)}</td>
                <td>{row.status}</td>
                <td>
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => {
                      setSelected(row);
                      setDecision(null);
                      setReason("");
                      setError("");
                    }}
                  >
                    View Request
                  </button>
                </td>
              </tr>
            ))}
            {!loading && !items.length && (
              <tr>
                <td colSpan={6}>No matching approval requests</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <Pager page={page} total={total} loading={loading} onPage={setPage} />
      {selected && (
        <Dialog
          title={"Approval #" + selected.id}
          busy={busy}
          onClose={() => setSelected(null)}
        >
          <div className="modal-body credit-form">
            <h3>{selected.label}</h3>
            <p>
              Requester / record creator: {selected.requester} · PKR{" "}
              {money(selected.amount)} · {selected.status}
            </p>
            <ReviewValues value={selected.details} />
            {selected.reason && <p>Decision reason: {selected.reason}</p>}
            {decision && (
              <label>
                Decision reason
                <textarea
                  required
                  maxLength={500}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            )}
            {error && (
              <p role="alert" className="modern-error">
                {error}
              </p>
            )}
            {!selected.canDecide && selected.status === "Pending" && (
              <p>
                An independent approver with current source access and a
                sufficient configured PKR limit must review this request.
              </p>
            )}
          </div>
          <div className="modal-foot">
            <button
              className="btn-secondary"
              disabled={busy}
              onClick={() => setSelected(null)}
            >
              Close
            </button>
            {selected.canDecide && !decision && (
              <>
                <button
                  className="btn-secondary"
                  onClick={() => setDecision("reject")}
                >
                  Reject
                </button>
                <button
                  className="btn-primary"
                  onClick={() => setDecision("approve")}
                >
                  Approve
                </button>
              </>
            )}
            {decision && (
              <button
                className="btn-primary"
                disabled={busy || !reason.trim()}
                onClick={() => void decide()}
              >
                Confirm {decision === "approve" ? "Approval" : "Rejection"}
              </button>
            )}
          </div>
        </Dialog>
      )}
      {controls && policy && (
        <Dialog
          title="Approval Controls"
          busy={busy}
          onClose={() => setControls(false)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void savePolicy();
            }}
          >
            <div className="modal-body credit-form">
              <p>
                Set the maximum PKR amount each role may approve per operation.
                Approval permission and source visibility are also required.
                Admin has no self-approval or amount-limit exemption. A missing
                limit grants no approval authority; zero permits only zero-value
                operations.
              </p>
              {!policy.enabled && (
                <p role="alert">
                  Approval enforcement is disabled in this environment.
                </p>
              )}
              <div className="form-grid">
                {policy.roles.map((role) => (
                  <label key={role}>
                    {role} limit (PKR)
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={limits[role] ?? ""}
                      placeholder="Not configured"
                      onChange={(e) =>
                        setLimits((current) => {
                          const next = { ...current };
                          if (e.target.value === "") delete next[role];
                          else next[role] = e.target.value;
                          return next;
                        })
                      }
                    />
                  </label>
                ))}
              </div>
              <label>
                Policy change reason
                <textarea
                  required
                  maxLength={500}
                  value={changeReason}
                  onChange={(e) => setChangeReason(e.target.value)}
                />
              </label>
              {error && (
                <p className="modern-error" role="alert">
                  {error}
                </p>
              )}
            </div>
            <div className="modal-foot">
              <button
                type="button"
                className="btn-secondary"
                disabled={busy}
                onClick={() => setControls(false)}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn-primary"
                disabled={busy || !changeReason.trim()}
              >
                Save Approval Limits
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </section>
  );
}
