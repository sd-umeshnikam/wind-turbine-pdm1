import { AlertOctagon, AlertTriangle, CheckCircle2, CircleDashed, Info, Loader2, X } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { ApiError } from "../api/client";
import type { AlertStatus, Severity } from "../api/types";
import { num } from "../lib/format";
import { BAND_LABEL, SEVERITY_LABEL, band, type Band } from "../lib/health";

export function Card({
  title,
  hint,
  tools,
  children,
  flush,
  className = "",
}: {
  title?: ReactNode;
  hint?: ReactNode;
  tools?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || tools) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {hint && <span className="hint">{hint}</span>}
          {tools && <div className="tools">{tools}</div>}
        </header>
      )}
      <div className={flush ? "card-body flush" : "card-body"}>{children}</div>
    </section>
  );
}

export function PageHead({
  title,
  lede,
  crumbs,
  actions,
}: {
  title: ReactNode;
  lede?: ReactNode;
  crumbs?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        {crumbs && <div className="crumbs">{crumbs}</div>}
        <h1>{title}</h1>
        {lede && <p className="lede" style={{ margin: "4px 0 0" }}>{lede}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

export function Kpi({
  label,
  value,
  foot,
  icon,
}: {
  label: ReactNode;
  value: ReactNode;
  foot?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="card kpi">
      <div className="kpi-label">
        {icon}
        {label}
      </div>
      <div className="kpi-value">{value}</div>
      {foot && <div className="kpi-foot">{foot}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- status badges (icon + label, never colour alone)

const BAND_DOT: Record<Band, string> = {
  good: "dot-good",
  watch: "dot-warning",
  degraded: "dot-serious",
  alarm: "dot-critical",
  none: "dot-none",
};
const BAND_BADGE: Record<Band, string> = {
  good: "good",
  watch: "warning",
  degraded: "serious",
  alarm: "critical",
  none: "neutral",
};

export function HealthBadge({ health, showValue = true }: { health: number | null | undefined; showValue?: boolean }) {
  const b = band(health);
  return (
    <span className={`badge ${BAND_BADGE[b]}`} title={`Health ${num(health)} / 100`}>
      <span className={`dot ${BAND_DOT[b]}`} aria-hidden />
      {showValue && b !== "none" ? `${num(health, 0)} · ${BAND_LABEL[b]}` : BAND_LABEL[b]}
    </span>
  );
}

export function HealthBar({ health }: { health: number | null | undefined }) {
  const b = band(health);
  return (
    <div className="hbar" title={`${BAND_LABEL[b]}: ${num(health)} / 100`}>
      <div className="hbar-track">
        <div className={`hbar-fill fill-${b}`} style={{ width: `${Math.max(0, Math.min(100, health ?? 0))}%` }} />
      </div>
      <span className="hbar-value">{num(health, 0)}</span>
    </div>
  );
}

const SEVERITY_BADGE: Record<Severity, string> = {
  critical: "critical",
  high: "serious",
  medium: "warning",
  low: "neutral",
};
const SEVERITY_ICON: Record<Severity, ReactNode> = {
  critical: <AlertOctagon size={13} aria-hidden />,
  high: <AlertTriangle size={13} aria-hidden />,
  medium: <AlertTriangle size={13} aria-hidden />,
  low: <Info size={13} aria-hidden />,
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`badge ${SEVERITY_BADGE[severity]}`}>
      {SEVERITY_ICON[severity]}
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

const STATUS_BADGE: Record<AlertStatus, [string, ReactNode, string]> = {
  open: ["critical", <CircleDashed size={13} aria-hidden key="o" />, "Open"],
  acknowledged: ["accent", <Loader2 size={13} aria-hidden key="a" />, "Acknowledged"],
  resolved: ["good", <CheckCircle2 size={13} aria-hidden key="r" />, "Resolved"],
};

export function StatusBadge({ status }: { status: AlertStatus }) {
  const [cls, icon, label] = STATUS_BADGE[status];
  return (
    <span className={`badge ${cls}`}>
      {icon}
      {label}
    </span>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

// ---------------------------------------------------------------- loading / empty / error

export function Loading({ label = "Loading…", height = 120 }: { label?: string; height?: number }) {
  return (
    <div className="skeleton" style={{ height }} role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function Empty({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="state">
      <div className="state-title">{title}</div>
      {children && <div>{children}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const status = error instanceof ApiError ? error.status : null;
  const message = error instanceof Error ? error.message : "Unexpected error";
  return (
    <div className="state error" role="alert">
      <div className="state-title">
        {status === 503 ? "Service temporarily unavailable" : status === 403 ? "Not permitted" : "Could not load data"}
      </div>
      <div>{message}</div>
      {retry && (
        <button className="btn sm" onClick={retry}>
          Retry
        </button>
      )}
    </div>
  );
}

/** Render a query: loading skeleton, error with retry, or the content. Never substitutes data. */
export function QueryView<T>({
  query,
  children,
  height,
}: {
  query: { data: T | undefined; error: unknown; isLoading: boolean; refetch: () => unknown };
  children: (data: T) => ReactNode;
  height?: number;
}) {
  if (query.isLoading) return <Loading height={height} />;
  if (query.error && query.data === undefined) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  if (query.data === undefined) return null;
  return <>{children(query.data)}</>;
}

// ---------------------------------------------------------------- tabs, drawer, dialog

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: ReactNode }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={t.id === value}
          className="tab"
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
}

export function Drawer({
  title,
  onClose,
  children,
  head,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  head?: ReactNode;
}) {
  useEscape(onClose);
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}>
        <div className="drawer-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2>{title}</h2>
            {head}
          </div>
          <button className="btn ghost icon" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  );
}

export function Dialog({ title, onClose, children }: { title: ReactNode; onClose: () => void; children: ReactNode }) {
  useEscape(onClose);
  return (
    <>
      <div className="overlay dialog-overlay" onClick={onClose} />
      <div className="dialog" role="dialog" aria-modal="true">
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ flex: 1 }}>{title}</h2>
          <button className="btn ghost icon" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </>
  );
}

export function Banner({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  return (
    <div className={`banner ${tone}`} role={tone === "error" ? "alert" : undefined}>
      {tone === "info" ? <Info size={16} /> : <AlertTriangle size={16} />}
      <div>{children}</div>
    </div>
  );
}
