import { useEffect, useRef, useState } from "react";
import { Dialog } from "./Dialog";
export function askDecisionReason(): Promise<string | null> {
  return new Promise((resolve) =>
    window.dispatchEvent(
      new CustomEvent("approval:reason", { detail: { resolve } }),
    ),
  );
}
export function ApprovalReasonPrompt() {
  const [open, setOpen] = useState(false),
    [reason, setReason] = useState("");
  const resolve = useRef<((value: string | null) => void) | null>(null);
  function finish(value: string | null) {
    resolve.current?.(value);
    resolve.current = null;
    setOpen(false);
    setReason("");
  }
  useEffect(() => {
    const handle = (event: Event) => {
      resolve.current?.(null);
      resolve.current = (
        event as CustomEvent<{ resolve: (value: string | null) => void }>
      ).detail.resolve;
      setReason("");
      setOpen(true);
    };
    window.addEventListener("approval:reason", handle);
    return () => {
      window.removeEventListener("approval:reason", handle);
      resolve.current?.(null);
    };
  }, []);
  return open ? (
    <Dialog
      title="Record Decision Reason"
      busy={false}
      onClose={() => finish(null)}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (reason.trim()) finish(reason.trim());
        }}
      >
        <div className="modal-body credit-form">
          <p>Your decision and reason will be recorded in the audit history.</p>
          <label>
            Decision reason
            <textarea
              required
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
        </div>
        <div className="modal-foot">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => finish(null)}
          >
            Cancel
          </button>
          <button className="btn-primary" disabled={!reason.trim()}>
            Confirm Decision
          </button>
        </div>
      </form>
    </Dialog>
  ) : null;
}
