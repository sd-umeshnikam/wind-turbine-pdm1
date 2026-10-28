// Health bands. Health is calibrated per model version so that 50 is the alarm level.

import type { Severity } from "../api/types";

export type Band = "good" | "watch" | "degraded" | "alarm" | "none";

export const BAND_LABEL: Record<Band, string> = {
  good: "Healthy",
  watch: "Watch",
  degraded: "Degraded",
  alarm: "Alarm",
  none: "No data",
};

export function band(health: number | null | undefined): Band {
  if (health === null || health === undefined) return "none";
  if (health < 50) return "alarm";
  if (health < 65) return "degraded";
  if (health < 80) return "watch";
  return "good";
}

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};
