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
import { colorForIndex } from "../../../shared/theme";

interface Props {
  summary: FleetSummary;
}

// One bar-chart row per farm, one bar series per fault category, built
// directly from anomaly_count_by_category per farm in fleet_summary.json.
export function FaultCategoryByFarmChart({ summary }: Props) {
  const farmIds = Object.keys(summary.farms);
  const categories = Array.from(
    new Set(farmIds.flatMap((id) => Object.keys(summary.farms[id].anomaly_count_by_category))),
  );

  const data = farmIds.map((farmId) => {
    const farm = summary.farms[farmId];
    const row: Record<string, string | number> = { farm: farm.label };
    for (const cat of categories) {
      row[cat] = farm.anomaly_count_by_category[cat] ?? 0;
    }
    return row;
  });

  return (
    <ResponsiveContainer width="100%" height={340}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="farm" tick={{ fontSize: 12 }} />
        <YAxis
          tick={{ fontSize: 12 }}
          label={{ value: "Anomaly events", angle: -90, position: "insideLeft", fontSize: 12 }}
          allowDecimals={false}
        />
        <Tooltip contentStyle={{ fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {categories.map((cat, i) => (
          <Bar key={cat} dataKey={cat} stackId="cat" fill={colorForIndex(i)} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
