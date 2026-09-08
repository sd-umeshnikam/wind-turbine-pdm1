import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { FleetSummary } from "../types";
import { HEALTH_COLORS } from "../../../shared/theme";

interface Props {
  summary: FleetSummary;
}

// Anomaly vs. normal reference-event counts per farm, straight from
// n_anomaly_events / n_normal_events in fleet_summary.json.
export function AnomalyVsNormalChart({ summary }: Props) {
  const data = Object.values(summary.farms).map((farm) => ({
    farm: farm.label,
    Anomaly: farm.n_anomaly_events,
    Normal: farm.n_normal_events,
  }));

  return (
    <ResponsiveContainer width="100%" height={340}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="farm" tick={{ fontSize: 12 }} />
        <YAxis
          tick={{ fontSize: 12 }}
          label={{ value: "Event count", angle: -90, position: "insideLeft", fontSize: 12 }}
          allowDecimals={false}
        />
        <Tooltip contentStyle={{ fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="Anomaly" fill={HEALTH_COLORS.red} />
        <Bar dataKey="Normal" fill={HEALTH_COLORS.green} />
      </BarChart>
    </ResponsiveContainer>
  );
}
