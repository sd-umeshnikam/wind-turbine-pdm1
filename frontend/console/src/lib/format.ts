// Formatting helpers. Data timestamps are on each turbine's own (anonymised) clock, so they
// are shown as UTC dates without a "time ago"; wall-clock timestamps (alerts, audit, jobs)
// are shown in the viewer's locale with a relative age.

const NA = "—";

export function num(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return NA;
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function int(v: number | null | undefined): string {
  if (v === null || v === undefined) return NA;
  return Math.round(v).toLocaleString();
}

export function pct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? NA : `${num(v * 100, digits)}%`;
}

export function withUnit(v: number | null | undefined, unit: string | null | undefined, digits = 1): string {
  const s = num(v, digits);
  return s === NA || !unit ? s : `${s} ${unit}`;
}

/** A data-clock timestamp (UTC, minute precision). */
export function dataTime(iso: string | null | undefined): string {
  if (!iso) return NA;
  return iso.replace("T", " ").slice(0, 16) + " UTC";
}

export function dataDate(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : NA;
}

/** A wall-clock timestamp in the viewer's locale. */
export function wallTime(iso: string | null | undefined): string {
  if (!iso) return NA;
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return NA;
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 0) return "in " + duration(-s);
  if (s < 45) return "just now";
  return duration(s) + " ago";
}

export function duration(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${Math.max(m, 1)} min`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h`;
  return `${Math.round(h / 24)} d`;
}

export function hoursBetween(a: string, b: string): number {
  return (new Date(b).getTime() - new Date(a).getTime()) / 3_600_000;
}

export function titleCase(code: string): string {
  return code.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function metricLabel(metric: string): string {
  return METRIC_LABELS[metric] ?? titleCase(metric);
}

const METRIC_LABELS: Record<string, string> = {
  care_style_score: "CARE-style score",
  event_recall: "Event recall (coverage)",
  event_precision: "Event precision",
  event_f1: "Event F1",
  normal_accuracy: "Accuracy on normal events",
  earliness: "Earliness",
  median_warning_hours: "Median warning (h)",
  false_alarm_events: "False-alarm events",
  false_alarm_days_per_turbine_year: "False-alarm days / turbine-year",
  pre_onset_alarm_events: "Pre-onset alarm events",
  diagnosis_accuracy: "Diagnosis accuracy",
  detected: "Detected anomaly events",
  anomaly_events: "Anomaly events",
  normal_events: "Normal events",
  mae_hours: "MAE (hours)",
  coverage_p10_p90: "P10–P90 coverage",
};
