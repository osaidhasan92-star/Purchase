import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import type { Bridge, User } from "../types";
export function FinanceNavigation({
  bridge,
  user,
  onNavigate,
}: {
  bridge: Bridge;
  user: User;
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, href: string) => void;
}) {
  const [open, setOpen] = useState("");
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const root = useRef<HTMLDivElement>(null),
    trigger = useRef<HTMLButtonElement | null>(null),
    menu = useRef<HTMLDivElement>(null);
  const query = new URLSearchParams(location.search),
    view = query.get("view") || "accounting",
    action = query.get("action");
  const link = (v: string, extra: Record<string, string> = {}) =>
    "erp.html?" +
    new URLSearchParams({ view: v, module: "accounting", ...extra });
  const groups = [
    {
      label: "Customers",
      views: ["customers", "sales-invoices", "sales-payments"],
      items: [
        ["Customer Invoices", link("sales-invoices"), "sales_invoices"],
        ["Customer Payments", link("sales-payments"), "sales_payments"],
        ["Customers", link("customers"), "sales_customers"],
      ],
    },
    {
      label: "Vendors",
      views: ["vendors", "invoices", "payments"],
      items: [
        ["Vendor Bills", link("invoices"), "invoices"],
        ["Vendor Payments", link("payments"), "payments"],
        ["Vendors", link("vendors"), "vendors"],
      ],
    },
    {
      label: "Accounting",
      views: ["journals", "aged"],
      items: [
        ["Journal Entries", link("journals"), "accounting"],
        ["Receivables & Payables", link("aged"), "accounting"],
      ],
    },
    {
      label: "Bank & Cash",
      views: ["bank"],
      items: [
        ["Bank Reconciliation", link("bank"), "accounting"],
        ...(bridge.can("accounting", "create") &&
        bridge.can("accounting", "approve")
          ? [
              [
                "Bank / Cash Transfer",
                link("accounting", { action: "transfer" }),
                "accounting",
              ],
            ]
          : []),
      ],
    },
    {
      label: "Reporting",
      views: ["reports"],
      items: [
        ["Financial Reports", link("reports"), "accounting"],
        ["Profit & Loss", link("reports", { report: "pnl" }), "accounting"],
        ["Balance Sheet", link("reports", { report: "balance" }), "accounting"],
        ["General Ledger", link("reports", { report: "ledger" }), "accounting"],
      ],
    },
    {
      label: "Configuration",
      views: ["accounts"],
      items: [
        ["Chart of Accounts", link("accounts"), "accounting"],
        ...(user.role === "Admin"
          ? [
              [
                "Period Lock",
                link("accounting", { action: "lock" }),
                "accounting",
              ],
            ]
          : []),
      ],
    },
  ]
    .map((g) => ({ ...g, items: g.items.filter(([, , p]) => bridge.can(p)) }))
    .filter((g) => g.items.length);
  const active =
    action === "transfer"
      ? "Bank & Cash"
      : action === "lock"
        ? "Configuration"
        : groups.find((g) => g.views.includes(view))?.label || "Dashboard";
  useEffect(() => {
    const close = (e: Event) => {
      if (!root.current?.contains(e.target as Node)) setOpen("");
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  useLayoutEffect(() => {
    if (!open || !root.current || !trigger.current || !menu.current) return;
    const box = root.current.getBoundingClientRect();
    const button = trigger.current.getBoundingClientRect();
    setPosition({
      left: Math.max(
        0,
        Math.min(button.left - box.left, box.width - menu.current.offsetWidth),
      ),
      top: button.bottom - box.top + 4,
    });
    const close = () => setOpen("");
    window.addEventListener("resize", close);
    return () => window.removeEventListener("resize", close);
  }, [open]);
  useEffect(() => {
    if (open) menu.current?.querySelector<HTMLElement>("a")?.focus();
  }, [open]);
  const group = groups.find((g) => g.label === open);
  return (
    <div
      className="finance-module-nav"
      ref={root}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          setOpen("");
          trigger.current?.focus();
        }
      }}
    >
      <nav className="module-tabs" aria-label="Accounting & Finance submenu">
        {bridge.can("accounting") && (
          <a
            href={link("accounting")}
            className={"module-tab" + (active === "Dashboard" ? " active" : "")}
            aria-current={active === "Dashboard" ? "page" : undefined}
            onClick={(e) => onNavigate(e, link("accounting"))}
          >
            Dashboard
          </a>
        )}
        {groups.map((g) => (
          <button
            key={g.label}
            className={"module-tab" + (active === g.label ? " active" : "")}
            type="button"
            aria-current={active === g.label ? "page" : undefined}
            aria-haspopup="menu"
            aria-expanded={open === g.label}
            onClick={(e) => {
              trigger.current = e.currentTarget;
              setOpen((v) => (v === g.label ? "" : g.label));
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                trigger.current = e.currentTarget;
                setOpen(g.label);
              }
            }}
          >
            {g.label}
          </button>
        ))}
      </nav>
      {group && (
        <div
          className="finance-submenu"
          style={position}
          role="menu"
          aria-label={group.label}
          ref={menu}
          onKeyDown={(e) => {
            if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key))
              return;
            e.preventDefault();
            const links = Array.from(
              menu.current?.querySelectorAll<HTMLAnchorElement>("a") || [],
            );
            const current = links.indexOf(
              document.activeElement as HTMLAnchorElement,
            );
            const next =
              e.key === "Home"
                ? 0
                : e.key === "End"
                  ? links.length - 1
                  : (current +
                      (e.key === "ArrowDown" ? 1 : -1) +
                      links.length) %
                    links.length;
            links[next]?.focus();
          }}
        >
          {group.items.map(([label, href]) => (
            <a
              role="menuitem"
              key={href}
              href={href}
              onClick={(e) => {
                setOpen("");
                onNavigate(e, href);
              }}
            >
              {label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
