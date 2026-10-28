// Time windows on a turbine's own data clock, ending at its replay cursor.

export const SPANS = [
  { value: 1, label: "24 h" },
  { value: 7, label: "7 d" },
  { value: 30, label: "30 d" },
  { value: 90, label: "90 d" },
  { value: 365, label: "1 y" },
] as const;

export type SpanDays = (typeof SPANS)[number]["value"];

/**
 * `from` = cursor - span, rounded down to the hour so the query key changes once an hour of
 * data time rather than on every replay tick (the API clips `to` to the live cursor).
 */
export function windowFrom(cursor: string | null | undefined, days: number): string | undefined {
  if (!cursor) return undefined;
  const t = new Date(cursor).getTime() - days * 86_400_000;
  const hour = Math.floor(t / 3_600_000) * 3_600_000;
  return new Date(hour).toISOString().replace(".000Z", "Z");
}
