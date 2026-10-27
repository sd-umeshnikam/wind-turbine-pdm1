import "./HealthPill.css";

type Tone = "success" | "warning" | "danger" | "critical" | "neutral";

const HEALTH_TONE: Record<"green" | "amber" | "red", Tone> = {
  green: "success",
  amber: "warning",
  red: "danger",
};

const SEVERITY_TONE: Record<string, Tone> = {
  low: "success",
  medium: "warning",
  high: "danger",
  critical: "critical",
};

export function Badge({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function HealthPill({ status, label }: { status: "green" | "amber" | "red"; label: string }) {
  return <Badge tone={HEALTH_TONE[status]}>{label}</Badge>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={SEVERITY_TONE[severity.toLowerCase()] ?? "warning"}>{severity}</Badge>;
}
