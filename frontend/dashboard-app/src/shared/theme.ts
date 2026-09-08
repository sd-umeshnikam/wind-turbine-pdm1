// Single source of truth for color semantics so severity/health read the same
// way in every module (fleet overview categories, alert badges, twin health pills).

export const HEALTH_COLORS: Record<"green" | "amber" | "red", string> = {
  green: "#2e8540",
  amber: "#d98a12",
  red: "#c8382c",
};

export const SEVERITY_COLORS: Record<string, string> = {
  low: HEALTH_COLORS.green,
  medium: HEALTH_COLORS.amber,
  high: HEALTH_COLORS.red,
  critical: HEALTH_COLORS.red,
};

// Distinct, colorblind-considerate categorical palette used for farms and
// fault categories across bar/line charts.
export const CATEGORICAL_PALETTE = [
  "#3b6fa0", // farm A / series 1
  "#5a9367", // farm B / series 2
  "#c17a2c", // farm C / series 3
  "#8a5fa8",
  "#c8382c",
  "#4f8fa6",
  "#a0783b",
  "#6f7c8a",
  "#b05c8a",
  "#7a9e3b",
];

export function colorForIndex(i: number): string {
  return CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length];
}
