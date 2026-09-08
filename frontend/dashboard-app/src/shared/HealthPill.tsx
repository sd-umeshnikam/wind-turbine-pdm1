import { HEALTH_COLORS, SEVERITY_COLORS } from "./theme";
import "./HealthPill.css";

export function HealthPill({ status, label }: { status: "green" | "amber" | "red"; label: string }) {
  return (
    <span className="health-pill" style={{ backgroundColor: HEALTH_COLORS[status] }}>
      {label}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const color = SEVERITY_COLORS[severity.toLowerCase()] ?? SEVERITY_COLORS.medium;
  return (
    <span className="health-pill" style={{ backgroundColor: color }}>
      {severity}
    </span>
  );
}
