import { useRef, useState, type FormEvent, type ReactNode } from "react";
import type { Bridge } from "../../types";
import { Dialog } from "../../components/Dialog";
import { Reference } from "../trade/Reference";
import { errorMessage } from "../../lib/api";
import {
  today,
  requestKey,
  money,
  str,
  type Journal,
  type Line,
  type Row,
} from "./types";
export type FormState = {
  kind:
    | "account"
    | "journal"
    | "edit-journal"
    | "transfer"
    | "statement"
    | "match-bank"
    | "reconcile"
    | "period-lock"
    | "reverse";
  record?: Row | Journal;
};
export function FinanceForm({
  form,
  bridge,
  onClose,
  onSaved,
}: {
  form: FormState;
  bridge: Bridge;
  onClose: () => void;
  onSaved: (record: Row) => void;
}) {
  const r = form.record,
    kind = form.kind;
  const [values, setValues] = useState<Record<string, unknown>>(() => ({
      date:
        kind === "period-lock"
          ? r?.date || ""
          : kind === "edit-journal"
            ? r?.date || today()
            : today(),
      memo: r?.memo || "",
      type: "asset",
      reconcile: false,
      fromAccount: "1010",
      toAccount: "1000",
      account: "1010",
      ...(kind === "match-bank" ? { id: r?.id, version: r?.version } : {}),
      ...(kind === "edit-journal" || kind === "reverse"
        ? { id: r?.id, version: r?.version }
        : {}),
      ...(kind === "period-lock" ? { version: r?.version } : {}),
    })),
    [lines, setLines] = useState<Line[]>(() =>
      kind === "edit-journal"
        ? (r as Journal).lines.map((l) => ({ ...l }))
        : [
            { account: "", debit: "", credit: "", partner: "" },
            { account: "", debit: "", credit: "", partner: "" },
          ],
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const locked = useRef(false),
    key = useRef(requestKey());
  const change = (k: string, v: unknown) =>
    setValues((x) => ({ ...x, [k]: v }));
  const field = (
    name: string,
    label: string,
    type = "text",
    required = true,
  ) => (
    <label>
      {label}
      <input
        name={name}
        aria-label={label}
        type={type}
        required={required}
        value={String(values[name] ?? "")}
        disabled={busy}
        onChange={(e) => change(name, e.target.value)}
        min={type === "number" ? "0.01" : undefined}
        step={type === "number" ? "0.01" : undefined}
        maxLength={name === "memo" ? 500 : 300}
      />
    </label>
  );
  const select = (name: string, label: string, options: [string, string][]) => (
    <label>
      {label}
      <select
        name={name}
        value={String(values[name] ?? "")}
        disabled={busy}
        onChange={(e) => change(name, e.target.value)}
      >
        {options.map(([value, label]) => (
          <option value={value} key={value}>
            {label}
          </option>
        ))}
      </select>
    </label>
  );
  const bank: [string, string][] = [
    ["1010", "Main Bank"],
    ["1000", "Cash on Hand"],
  ];
  const titles = {
    account: "New Account",
    journal: "New Journal Entry",
    "edit-journal": "Edit Draft Journal",
    transfer: "Bank / Cash Transfer",
    statement: "New Statement Line",
    "match-bank": "Match Statement",
    reconcile: "Match Open Items",
    "period-lock": "Accounting Period Lock",
    reverse: "Reverse Journal",
  };
  const button = {
    account: "Save Account",
    journal: "Save Draft",
    "edit-journal": "Save Draft",
    transfer: "Post Transfer",
    statement: "Save Statement",
    "match-bank": "Match Statement",
    reconcile: "Match Items",
    "period-lock": "Save Lock",
    reverse: "Reverse Journal",
  };
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      let payload: Record<string, unknown> = { requestKey: key.current };
      const fields: Record<string, string[]> = {
        account: ["code", "name", "type", "reconcile"],
        journal: ["date", "memo"],
        "edit-journal": ["id", "version", "date", "memo"],
        transfer: ["date", "fromAccount", "toAccount", "amount"],
        statement: ["date", "account", "description", "amount"],
        "match-bank": ["id", "version", "lineId", "lineVersion"],
        reconcile: [
          "debitLine",
          "creditLine",
          "debitVersion",
          "creditVersion",
          "amount",
        ],
        "period-lock": ["date", "version"],
        reverse: ["id", "version", "date"],
      };
      for (const f of fields[kind])
        if (values[f] !== undefined) payload[f] = values[f];
      if (kind === "journal" || kind === "edit-journal")
        payload.lines = lines.map((l) => ({
          account: l.account,
          debit: l.debit || "0",
          credit: l.credit || "0",
          partner: l.partner,
          dueDate: l.dueDate || null,
        }));
      const result = await bridge.request<{ record: Row }>(
        "/finance/commands/" + kind,
        { method: "POST", body: JSON.stringify(payload) },
      );
      bridge.toast("Accounting record saved");
      onSaved(result.record);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  let body: ReactNode = null;
  if (kind === "account")
    body = (
      <>
        {field("code", "Account code")}
        {field("name", "Account name")}
        {select(
          "type",
          "Account type",
          ["asset", "liability", "equity", "income", "expense"].map((x) => [
            x,
            x,
          ]),
        )}
        <label>
          Allow reconciliation
          <select
            name="reconcile"
            value={String(values.reconcile)}
            onChange={(e) => change("reconcile", e.target.value === "true")}
            disabled={busy}
          >
            <option value="false">Disabled</option>
            <option value="true">Enabled</option>
          </select>
        </label>
      </>
    );
  if (kind === "journal" || kind === "edit-journal")
    body = (
      <>
        {field("memo", "Memo")}
        {field("date", "Journal date", "date")}
      </>
    );
  if (kind === "transfer")
    body = (
      <>
        {select("fromAccount", "From account", bank)}
        {select("toAccount", "To account", bank)}
        {field("amount", "Transfer amount (PKR)", "number")}
        {field("date", "Transfer date", "date")}
      </>
    );
  if (kind === "statement")
    body = (
      <>
        {field("description", "Statement description")}
        {field("date", "Statement date", "date")}
        {select("account", "Statement account", bank)}
        <label>
          Signed amount (PKR)
          <input
            name="amount"
            type="number"
            step="0.01"
            required
            value={String(values.amount ?? "")}
            disabled={busy}
            onChange={(e) => change("amount", e.target.value)}
          />
        </label>
      </>
    );
  if (kind === "period-lock")
    body = (
      <>
        {field("date", "Lock through", "date", false)}
        <p>
          Posting on or before this date will be blocked. Clear the date to
          unlock. Administrator action.
        </p>
      </>
    );
  if (kind === "reverse")
    body = (
      <>
        <p>
          Reverse {str(r?.number)} on the selected date. Matched items require
          accounting review first.
        </p>
        {field("date", "Reversal date", "date")}
      </>
    );
  if (kind === "match-bank")
    body = (
      <>
        <p>
          {str(r?.description)} · PKR {money(r?.amount)}
        </p>
        <Reference
          bridge={bridge}
          path={"/finance/statements/" + r?.id + "/candidates"}
          name="lineId"
          label="Matching journal item"
          value={String(values.lineId || "")}
          required
          disabled={busy}
          onSelect={(rows) => {
            change("lineId", rows[0]?.id);
            change("lineVersion", rows[0]?.version);
          }}
        />
        <p>
          Only unused posted journal items with the same account and signed
          amount are eligible. Matching creates no payment.
        </p>
      </>
    );
  if (kind === "reconcile")
    body = (
      <>
        <Reference
          bridge={bridge}
          path="/finance/open-items?side=debit"
          name="debitLine"
          label="Debit item"
          value={String(values.debitLine || "")}
          required
          disabled={busy}
          onSelect={(rows) => {
            const d = rows[0];
            setValues((v) => ({
              ...v,
              debitLine: d?.id,
              debitVersion: d?.version,
              debitAccount: d?.account,
              debitPartner: d?.partner,
              creditLine: "",
              creditVersion: "",
              amount: d?.openAmount || "",
            }));
          }}
        />
        {values.debitLine && (
          <Reference
            bridge={bridge}
            path={
              "/finance/open-items?" +
              new URLSearchParams({
                side: "credit",
                account: String(values.debitAccount),
                partner: String(values.debitPartner || ""),
              })
            }
            name="creditLine"
            label="Credit item"
            value={String(values.creditLine || "")}
            required
            disabled={busy}
            onSelect={(rows) => {
              change("creditLine", rows[0]?.id);
              change("creditVersion", rows[0]?.version);
              change(
                "amount",
                Math.min(
                  Number(values.amount || 0),
                  Number(rows[0]?.openAmount || 0),
                ).toFixed(2),
              );
            }}
          />
        )}
        {field("amount", "Matching amount (PKR)", "number")}
        <p>
          Match posted AR/AP items on the same account and partner. Partial
          matching is supported.
        </p>
      </>
    );
  return (
    <Dialog title={titles[kind]} busy={busy} onClose={onClose}>
      <form
        className="trade-form finance-form"
        onSubmit={(e) => void submit(e)}
      >
        <div className="form-grid">{body}</div>
        {(kind === "journal" || kind === "edit-journal") && (
          <>
            <p>
              Enter a debit OR credit per line; totals must balance. Use
              consistent partner keys for matching.
            </p>
            {lines.map((l, i) => (
              <fieldset className="finance-line" key={i}>
                <legend>Journal line {i + 1}</legend>
                <Reference
                  bridge={bridge}
                  path="/finance/accounts"
                  name={"account-" + i}
                  label={"Account " + (i + 1)}
                  value={l.account}
                  required
                  disabled={busy}
                  pinned={l.account ? [{ id: l.account, name: l.account }] : []}
                  onSelect={(items) =>
                    setLines((rows) =>
                      rows.map((r, n) =>
                        n === i
                          ? { ...r, account: String(items[0]?.id || "") }
                          : r,
                      ),
                    )
                  }
                />
                <div className="form-grid">
                  {(["debit", "credit", "partner", "dueDate"] as const).map(
                    (k) => (
                      <label key={k}>
                        {k === "dueDate"
                          ? "Due date"
                          : k.charAt(0).toUpperCase() + k.slice(1)}{" "}
                        {i + 1}
                        <input
                          aria-label={
                            (k === "dueDate"
                              ? "Due date"
                              : k.charAt(0).toUpperCase() + k.slice(1)) +
                            " " +
                            (i + 1)
                          }
                          name={k + "-" + i}
                          type={
                            k === "dueDate"
                              ? "date"
                              : k === "partner"
                                ? "text"
                                : "number"
                          }
                          step={
                            k === "debit" || k === "credit" ? "0.01" : undefined
                          }
                          min={
                            k === "debit" || k === "credit" ? "0" : undefined
                          }
                          maxLength={k === "partner" ? 100 : undefined}
                          value={l[k] || ""}
                          disabled={busy}
                          onChange={(e) =>
                            setLines((rows) =>
                              rows.map((r, n) =>
                                n === i ? { ...r, [k]: e.target.value } : r,
                              ),
                            )
                          }
                        />
                      </label>
                    ),
                  )}
                </div>
                {lines.length > 2 && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      setLines((rows) => rows.filter((_, n) => n !== i))
                    }
                  >
                    Remove line {i + 1}
                  </button>
                )}
              </fieldset>
            ))}
            <button
              type="button"
              disabled={busy || lines.length >= 100}
              onClick={() =>
                setLines((rows) => [
                  ...rows,
                  { account: "", debit: "", credit: "", partner: "" },
                ])
              }
            >
              Add Line
            </button>
            <p>
              Debit: PKR{" "}
              {money(lines.reduce((n, l) => n + Number(l.debit || 0), 0))} ·
              Credit: PKR{" "}
              {money(lines.reduce((n, l) => n + Number(l.credit || 0), 0))}
            </p>
          </>
        )}
        {error && (
          <p className="modern-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-foot">
          <button type="button" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={busy}>
            {busy ? "Saving…" : button[kind]}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
