import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Bridge } from "../../types";
import { Dialog } from "../../components/Dialog";
import { Reference } from "../trade/Reference";
import { errorMessage } from "../../lib/api";
import { money, today, requestKey } from "./types";
type Credit = {
  id: number;
  number: string;
  kind: string;
  invoiceId: string;
  invoiceNumber: string;
  partner: string;
  date: string;
  status: string;
  amount: string;
  tax: string;
  remaining: string;
  reason: string;
  version: string;
  actions: string[];
  lines: {
    lineIndex: number;
    quantity: string;
    amount: string;
    returnId: number | null;
    returnNumber: string | null;
  }[];
  settlements: {
    id: number;
    kind: string;
    invoiceId: string | null;
    amount: string;
    date: string;
    journalId: number | null;
    journalSource: string | null;
  }[];
  journalId: number | null;
};
type Source = {
  invoice: { id: string; invoiceNo: string };
  lines: {
    index: number;
    product: string;
    remaining: string;
    stock: boolean;
    returns: { id: number; number: string; date: string; remaining: string }[];
  }[];
};
const labels: Record<string, string> = {
  submit: "Submit for Review",
  post: "Post Credit Note",
  reset: "Return to Draft",
  cancel: "Cancel Credit Note",
  refund: "Register Refund",
  apply: "Apply to Invoice / Bill",
};
export function CreditsPage({ bridge }: { bridge: Bridge }) {
  const params = new URLSearchParams(location.search),
    kind = params.get("kind") === "vendor" ? "vendor" : "customer";
  const [items, setItems] = useState<Credit[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(1),
    [reload, setReload] = useState(0),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [detail, setDetail] = useState<Credit | null>(null),
    [creating, setCreating] = useState(
      bridge.can("accounting", "create") &&
        (!!params.get("invoiceId") || params.get("new") === "1"),
    ),
    [invoiceId, setInvoiceId] = useState(params.get("invoiceId") || ""),
    [source, setSource] = useState<Source | null>(null),
    [quantities, setQuantities] = useState<Record<number, string>>({}),
    [returns, setReturns] = useState<Record<number, string>>({}),
    [date, setDate] = useState(today()),
    [reason, setReason] = useState(""),
    [settling, setSettling] = useState<"refund" | "apply" | null>(null),
    [amount, setAmount] = useState(""),
    [target, setTarget] = useState(""),
    [bank, setBank] = useState("1010"),
    [busy, setBusy] = useState(false);
  const pending = useRef(false),
    keys = useRef(new Map<string, string>());
  useEffect(() => {
    const identity = new URLSearchParams(location.search).get("creditId");
    if (!identity) return;
    let active = true;
    bridge
      .request<{ record: Credit }>("/credits/" + encodeURIComponent(identity))
      .then((r) => {
        if (active) setDetail(r.record);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [bridge]);
  const invoiceResource = kind === "customer" ? "customerInvoices" : "invoices";
  const invoiceView = kind === "customer" ? "sales-invoices" : "invoices";
  useEffect(() => {
    let active = true;
    setLoading(true);
    bridge
      .request<{ items: Credit[]; total: number }>(
        "/credits?" +
          new URLSearchParams({ kind, page: String(page), pageSize: "25" }),
      )
      .then((r) => {
        if (active) {
          setItems(r.items);
          setTotal(r.total);
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
  }, [kind, page, reload, bridge]);
  useEffect(() => {
    let active = true;
    setSource(null);
    setQuantities({});
    setReturns({});
    if (!invoiceId) return;
    bridge
      .request<Source>(
        "/credits/source/" + kind + "/" + encodeURIComponent(invoiceId),
      )
      .then((r) => {
        if (active) setSource(r);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [kind, invoiceId, bridge]);
  const command = async (
    action: string,
    payload: Record<string, unknown>,
    note?: Credit,
  ) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const signature = JSON.stringify({ action, payload, id: note?.id });
    let key = keys.current.get(signature);
    if (!key) {
      key = requestKey();
      keys.current.set(signature, key);
    }
    try {
      const r = await bridge.request<{ record: Credit }>(
        "/credits/commands/" + action,
        {
          method: "POST",
          body: JSON.stringify({
            ...payload,
            ...(note ? { id: note.id, version: note.version } : {}),
            requestKey: key,
          }),
        },
      );
      keys.current.delete(signature);
      setDetail(r.record);
      setCreating(false);
      setSettling(null);
      setReload((v) => v + 1);
      bridge.toast("Credit " + action + " completed");
    } catch (e) {
      setError(errorMessage(e));
      if (note) {
        try {
          setDetail(
            (await bridge.request<{ record: Credit }>("/credits/" + note.id))
              .record,
          );
        } catch {}
      }
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const create = (event: FormEvent) => {
    event.preventDefault();
    void command("create", {
      kind,
      invoiceId,
      date,
      reason,
      lines: (source?.lines || [])
        .filter((l) => Number(quantities[l.index]) > 0)
        .map((l) => ({
          lineIndex: l.index,
          quantity: quantities[l.index],
          ...(l.stock ? { returnId: Number(returns[l.index]) } : {}),
        })),
    });
  };
  return (
    <section
      className="section-card"
      data-screen="credits-react"
      data-native-finance="credits"
      aria-busy={loading}
    >
      <div className="section-head">
        <div>
          <h2>
            {kind === "customer"
              ? "Customer Credit Notes"
              : "Vendor Credit Notes"}
          </h2>
          <p className="hint">
            Validated return → Draft credit → Finance posts → Apply credit or
            refund · PKR
          </p>
        </div>
        {bridge.can("accounting", "create") && (
          <button
            className="btn-primary"
            onClick={() => {
              setError("");
              setInvoiceId("");
              setReason("");
              setDate(today());
              setCreating(true);
            }}
          >
            New Credit Note
          </button>
        )}
      </div>
      {error && !creating && !detail && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      <div className="finance-table-wrap">
        <table>
          <thead>
            <tr>
              <th>Credit Note</th>
              <th>Date</th>
              <th>Original Document</th>
              <th>Partner</th>
              <th>Status</th>
              <th>Amount</th>
              <th>Available Credit</th>
            </tr>
          </thead>
          <tbody>
            {items.map((n) => (
              <tr key={n.id}>
                <td>
                  <button className="btn-sm" onClick={() => setDetail(n)}>
                    {n.number}
                  </button>
                </td>
                <td>{n.date}</td>
                <td>
                  <a
                    href={
                      "erp.html?view=" +
                      invoiceView +
                      "&module=accounting&search=" +
                      encodeURIComponent(n.invoiceNumber)
                    }
                  >
                    {n.invoiceNumber}
                  </a>
                </td>
                <td>{n.partner}</td>
                <td>{n.status}</td>
                <td>{money(n.amount)}</td>
                <td>{money(n.remaining)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !items.length && (
          <p className="empty">No credit notes found.</p>
        )}
      </div>
      <div className="section-head">
        <button
          className="btn-sm"
          disabled={page === 1 || loading}
          onClick={() => setPage((v) => v - 1)}
        >
          Previous
        </button>
        <span>
          Page {page} · {total} credit notes
        </span>
        <button
          className="btn-sm"
          disabled={page * 25 >= total || loading}
          onClick={() => setPage((v) => v + 1)}
        >
          Next
        </button>
      </div>
      {creating && (
        <Dialog
          busy={busy}
          title="New Credit Note"
          onClose={() => {
            if (!busy) setCreating(false);
          }}
        >
          <form className="modal-body credit-form" onSubmit={create}>
            {error && (
              <p role="alert" className="error-message">
                {error}
              </p>
            )}
            <p className="hint">
              For stock products, validate the return from Inventory first.
              Select only the quantities to credit. For services, no stock
              return is required.
            </p>
            <Reference
              bridge={bridge}
              path={
                "/trade/" +
                invoiceResource +
                "?status=Posted|Approved|Partially Paid|Paid"
              }
              label="Original Invoice / Bill"
              name="creditInvoice"
              value={invoiceId}
              onSelect={(v) => setInvoiceId(String(v[0]?.id || ""))}
              required
            />
            {source && <p>Original document: {source.invoice.invoiceNo}</p>}
            <label>
              Credit Date
              <input
                aria-label="Credit Date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                required
              />
            </label>
            <label>
              Reason
              <textarea
                aria-label="Credit Reason"
                maxLength={500}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                required
              />
            </label>
            {source?.lines.map((l) => (
              <fieldset key={l.index}>
                <legend>
                  {l.product} · Uncredited quantity: {l.remaining}
                </legend>
                <label>
                  Credit quantity
                  <input
                    aria-label={"Credit Quantity " + (l.index + 1)}
                    type="number"
                    min="0"
                    max={l.remaining}
                    step="0.0001"
                    value={quantities[l.index] || ""}
                    onChange={(e) =>
                      setQuantities({
                        ...quantities,
                        [l.index]: e.target.value,
                      })
                    }
                  />
                </label>
                {l.stock && (
                  <label>
                    Validated stock return
                    <select
                      aria-label={"Stock Return " + (l.index + 1)}
                      value={returns[l.index] || ""}
                      onChange={(e) =>
                        setReturns({ ...returns, [l.index]: e.target.value })
                      }
                      required={Number(quantities[l.index]) > 0}
                    >
                      <option value="">Select return</option>
                      {l.returns.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.number} · {r.date} · Available {r.remaining}
                        </option>
                      ))}
                    </select>
                    {!l.returns.length && (
                      <p className="hint">
                        No uncredited stock returns available for this line.
                      </p>
                    )}
                  </label>
                )}
              </fieldset>
            ))}
            <div className="form-actions">
              <button
                type="button"
                className="btn-sm"
                disabled={busy}
                onClick={() => setCreating(false)}
              >
                Cancel
              </button>
              <button className="btn-primary" disabled={busy || !source}>
                Save Draft Credit
              </button>
            </div>
          </form>
        </Dialog>
      )}
      {detail && !creating && (
        <Dialog
          busy={busy}
          title={detail.number}
          onClose={() => {
            if (!busy) {
              setDetail(null);
              setSettling(null);
            }
          }}
        >
          <div className="modal-body credit-dialog-body">
            {error && (
              <p role="alert" className="error-message">
                {error}
              </p>
            )}
            <p>
              {detail.partner} · Original {detail.invoiceNumber} ·{" "}
              {detail.status}
            </p>
            <p>{detail.reason}</p>
            <p>
              Credit PKR {money(detail.amount)} · Tax {money(detail.tax)} ·
              Available PKR {money(detail.remaining)}
            </p>
            <div className="finance-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Invoice line</th>
                    <th>Quantity</th>
                    <th>Return</th>
                    <th>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.lines.map((l) => (
                    <tr key={l.lineIndex}>
                      <td>{l.lineIndex + 1}</td>
                      <td>{l.quantity}</td>
                      <td>
                        {l.returnId ? (
                          <a
                            href={
                              "erp.html?view=stock-moves&search=" +
                              encodeURIComponent(l.returnNumber || "")
                            }
                          >
                            Stock return #{l.returnId}
                          </a>
                        ) : (
                          "Service"
                        )}
                      </td>
                      <td>{money(l.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {detail.journalId && (
              <p>
                <a href={"erp.html?view=journals&source=credit:" + detail.id}>
                  View posted journal
                </a>
              </p>
            )}
            {detail.settlements.length > 0 && (
              <>
                <h3>Credit Applications & Refunds</h3>
                {detail.settlements.map((s) => (
                  <p key={s.id}>
                    {s.date} ·{" "}
                    {s.kind === "refund"
                      ? kind === "customer"
                        ? "Refund paid"
                        : "Refund received"
                      : "Applied to document #" + s.invoiceId}{" "}
                    · PKR {money(s.amount)}
                    {s.journalId && (
                      <>
                        {" "}
                        ·{" "}
                        <a
                          href={
                            "erp.html?view=journals&source=" +
                            encodeURIComponent(s.journalSource || "")
                          }
                        >
                          Journal #{s.journalId}
                        </a>
                      </>
                    )}
                  </p>
                ))}
              </>
            )}
            {settling ? (
              <form
                className="credit-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void command(
                    settling,
                    {
                      amount,
                      date,
                      ...(settling === "refund"
                        ? { account: bank }
                        : { invoiceId: target }),
                    },
                    detail,
                  );
                }}
              >
                <h3>
                  {settling === "refund"
                    ? kind === "customer"
                      ? "Pay Customer Refund"
                      : "Receive Vendor Refund"
                    : "Apply Available Credit"}
                </h3>
                <label>
                  Settlement Date
                  <input
                    aria-label="Settlement Date"
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    required
                  />
                </label>
                <label>
                  Amount (PKR)
                  <input
                    aria-label="Settlement Amount"
                    type="number"
                    min="0.01"
                    max={detail.remaining}
                    step="0.01"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    required
                  />
                </label>
                {settling === "refund" ? (
                  <label>
                    Bank / Cash
                    <select
                      aria-label="Refund Account"
                      value={bank}
                      onChange={(e) => setBank(e.target.value)}
                    >
                      <option value="1010">Main Bank</option>
                      <option value="1000">Cash on Hand</option>
                    </select>
                  </label>
                ) : (
                  <Reference
                    bridge={bridge}
                    path={
                      "/trade/" +
                      invoiceResource +
                      "?status=Posted|Approved|Partially Paid"
                    }
                    label="Open Invoice / Bill"
                    name="creditTarget"
                    value={target}
                    onSelect={(v) => setTarget(String(v[0]?.id || ""))}
                    required
                  />
                )}
                <div className="form-actions">
                  <button
                    type="button"
                    className="btn-sm"
                    disabled={busy}
                    onClick={() => setSettling(null)}
                  >
                    Cancel Settlement
                  </button>
                  <button className="btn-primary" disabled={busy}>
                    {settling === "refund" ? "Confirm Refund" : "Apply Credit"}
                  </button>
                </div>
              </form>
            ) : (
              <div className="form-actions">
                {detail.actions.map((a) => (
                  <button
                    className="btn-sm"
                    key={a}
                    disabled={busy}
                    onClick={() => {
                      if (a === "refund" || a === "apply") {
                        setAmount(detail.remaining);
                        setDate(today());
                        setTarget("");
                        setSettling(a);
                      } else void command(a, {}, detail);
                    }}
                  >
                    {labels[a]}
                  </button>
                ))}
                <button
                  className="btn-sm"
                  disabled={busy}
                  onClick={() => setDetail(null)}
                >
                  Close
                </button>
              </div>
            )}
          </div>
        </Dialog>
      )}
    </section>
  );
}
