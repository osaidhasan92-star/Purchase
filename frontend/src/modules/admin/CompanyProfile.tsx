import { useEffect, useRef, useState } from "react";
import type { Bridge } from "../../types";
import { Dialog } from "../../components/Dialog";
import { errorMessage } from "../../lib/api";
import { requestKey } from "../finance/types";
export function CompanyProfile({
  bridge,
  onClose,
}: {
  bridge: Bridge;
  onClose: () => void;
}) {
  const [record, setRecord] = useState<{
      values: Record<string, string>;
      version: string;
    } | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const locked = useRef(false),
    key = useRef(requestKey());
  useEffect(() => {
    let active = true;
    bridge
      .request<{ record: { values: Record<string, string>; version: string } }>(
        "/administration/company",
      )
      .then((r) => {
        if (active) setRecord(r.record);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [bridge]);
  async function save(form: HTMLFormElement) {
    if (!record || locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      await bridge.request("/administration/commands/company", {
        method: "POST",
        body: JSON.stringify({
          ...Object.fromEntries(new FormData(form)),
          version: record.version,
          requestKey: key.current,
        }),
      });
      location.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <Dialog title="Company profile" busy={busy} onClose={onClose}>
      <form
        className="trade-form"
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
        <p>Pakistan · PKR · One company · WH / Stock</p>
        {record ? (
          <div className="form-grid">
            {[
              ["name", "Company name"],
              ["legalName", "Legal name"],
              ["address", "Address"],
              ["phone", "Telephone"],
              ["email", "Email"],
              ["taxNumber", "NTN / STRN"],
            ].map(([k, label]) => (
              <label key={k}>
                {label}
                <input
                  id={"profile-" + k}
                  name={k}
                  required={k === "name"}
                  maxLength={500}
                  defaultValue={record.values[k] || ""}
                />
              </label>
            ))}
          </div>
        ) : (
          <p role="status">Loading company profile…</p>
        )}
        <div className="modal-foot">
          <button
            className="btn-secondary"
            type="button"
            disabled={busy}
            onClick={onClose}
          >
            Cancel
          </button>
          <button className="btn-primary" disabled={busy || !record}>
            Save
          </button>
        </div>
      </form>
    </Dialog>
  );
}
