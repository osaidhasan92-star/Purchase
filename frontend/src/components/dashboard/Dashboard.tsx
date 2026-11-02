import { useEffect, useId, useRef, useState, type ReactNode } from "react";
export const money = (value: number) =>
  "Rs " +
  Number(value || 0).toLocaleString("en-PK", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
export function DashboardFrame({
  module,
  children,
}: {
  module: string;
  children: ReactNode;
}) {
  return (
    <div
      className="reference-dashboard unified-dashboard"
      data-dashboard={module}
    >
      <div className="ref-dashboard-content" aria-busy="false">
        {children}
      </div>
    </div>
  );
}
export function Icon({ kind = "chart" }: { kind?: string }) {
  const paths: Record<string, string> = {
    home: "m3 11 9-8 9 8M5 10v11h5v-7h4v7h5V10",
    cart: "M3 4h2l3 12h10l3-8H6M9 20h1m7 0h1",
    box: "m3 7 9-4 9 4v10l-9 4-9-4V7zm0 0 9 4 9-4m-9 4v10",
    factory: "M3 21V9l6 3V7l6 3V3h5v18H3zM7 16h1m4 0h1m4 0h1",
    settings:
      "m9 3-1 3-3 1-2 4 2 2 1 4 3 1 2 3 4-1 1-3 3-2-1-4 1-3-4-2-2-2H9zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
    chart: "M4 19h16M7 15V9m5 6V5m5 10v-4",
    order: "M7 4h10v16l-5-3-5 3z",
    cash: "M3 6h18v12H3zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
    clock: "M12 8v4l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
    file: "M6 3h8l4 4v14H6zM9 11h6m-6 4h6",
    people: "M16 21v-3a4 4 0 0 0-8 0v3M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
  };
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <path d={paths[kind] || paths.chart} />
    </svg>
  );
}
export function Kpi({
  label,
  value,
  hint,
  tone = "navy",
  icon,
}: {
  label: string;
  value: ReactNode;
  hint: string;
  tone?: string;
  icon?: string;
}) {
  return (
    <article className={"ref-kpi tone-" + tone}>
      <div className="ref-kpi-label">
        {label}
        <span>
          <Icon kind={icon} />
        </span>
      </div>
      <strong>{value}</strong>
      <small>{hint}</small>
    </article>
  );
}
export function Panel({
  title,
  kicker,
  subtitle,
  action,
  children,
  className = "",
}: {
  title: string;
  kicker?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={"ref-panel " + className}>
      <header className="ref-panel-head">
        <div>
          {kicker && <span className="ref-kicker">{kicker}</span>}
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}
export function Trend({
  rows,
  secondary,
  color = "#232e78",
  title,
}: {
  rows: { month: string; value: number; second?: number }[];
  secondary?: boolean;
  color?: string;
  title: string;
}) {
  const id = useId().replace(/:/g, "");
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const measure = () => {
      const style = getComputedStyle(element);
      const value =
        element.clientWidth -
        parseFloat(style.paddingLeft) -
        parseFloat(style.paddingRight);
      if (value > 0) setWidth(Math.max(280, value));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const max = Math.max(1, ...rows.flatMap((r) => [r.value, r.second || 0]));
  const x = (i: number) =>
      28 + (i * (width - 56)) / Math.max(1, rows.length - 1),
    y = (value: number) => 190 - (value / max) * 150;
  const points = (second = false) =>
    rows
      .map((r, i) => `${x(i)},${y(second ? r.second || 0 : r.value)}`)
      .join(" ");
  return (
    <div className="ref-chart" ref={container}>
      <svg viewBox={`0 0 ${width} 235`} role="img" aria-label={title}>
        <title>{title}</title>
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity=".15" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[40, 78, 116, 154, 190].map((v) => (
          <line
            key={v}
            x1="22"
            x2={width - 20}
            y1={v}
            y2={v}
            stroke="#edf0f7"
          />
        ))}
        <polygon
          points={`28,190 ${points()} ${width - 28},190`}
          fill={`url(#${id})`}
        />
        <polyline
          points={points()}
          stroke={color}
          strokeWidth="3"
          fill="none"
        />
        {secondary && (
          <polyline
            points={points(true)}
            stroke="#95a4bd"
            strokeWidth="2"
            strokeDasharray="5 4"
            fill="none"
          />
        )}
        {rows.map((r, i) => (
          <g key={r.month}>
            <circle
              cx={x(i)}
              cy={y(r.value)}
              r="4"
              fill={color}
              stroke="white"
              strokeWidth="2"
            >
              <title>{r.month + ": " + money(r.value)}</title>
            </circle>
            <text x={x(i)} y="219" textAnchor="middle">
              {new Date(r.month + "-02T12:00:00").toLocaleDateString("en", {
                month: "short",
              })}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
export function Funnel({
  rows,
  color,
}: {
  rows: { label: string; count: number }[];
  color?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div className="ref-funnel">
      {rows.map((r, i) => (
        <div key={r.label}>
          <div className="ref-funnel-label">
            <span>{r.label}</span>
            <b>{r.count}</b>
          </div>
          <div className="ref-track">
            <span
              style={{
                width: (r.count / max) * 100 + "%",
                background:
                  color ||
                  ["#253b93", "#8060d9", "#12a4ac", "#e3a12d", "#347de4"][
                    i % 5
                  ],
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
export function Health({
  rows,
}: {
  rows: { label: string; value: number; icon?: string }[];
}) {
  return (
    <div className="ref-health">
      {rows.map((r, i) => (
        <div key={r.label}>
          <Icon kind={r.icon} />
          <strong>{r.value}</strong>
          <small>{r.label}</small>
        </div>
      ))}
    </div>
  );
}
export function DashboardLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <a className="ref-link" href={href}>
      {children}
    </a>
  );
}
