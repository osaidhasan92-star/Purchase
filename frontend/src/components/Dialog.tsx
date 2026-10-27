import { useEffect, useRef, type ReactNode } from "react";
export function Dialog({
  title,
  busy,
  onClose,
  children,
}: {
  title: string;
  busy: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null),
    close = useRef(onClose),
    locked = useRef(busy);
  close.current = onClose;
  locked.current = busy;
  useEffect(() => {
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const el = ref.current;
    if (!el) return;
    const targets = () =>
      Array.from(
        el.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]',
        ),
      );
    targets()[0]?.focus();
    const handle = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !locked.current) {
        e.preventDefault();
        close.current();
      }
      if (e.key === "Tab") {
        const all = targets(),
          first = all[0],
          last = all[all.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    el.addEventListener("keydown", handle);
    return () => {
      el.removeEventListener("keydown", handle);
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <div className="modal is-open">
      <div
        className="modal-box request-modal wide trade-dialog"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="trade-dialog-title"
      >
        <div className="modal-head">
          <h3 id="trade-dialog-title">{title}</h3>
          <button
            type="button"
            aria-label="Close dialog"
            disabled={busy}
            onClick={onClose}
          >
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
