import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getPredictions } from "../../api/client";
import type { Prediction } from "../../api/types";
import { StatTile } from "../../shared/StatTile";
import { HEALTH_COLORS } from "../../shared/theme";
import "./ForecastsRulPage.css";

// Calendar-approximate: 30-day months, 365-day years. Shows the two largest non-zero units.
function formatRul(hours: number): string {
  if (hours < 24) return `${Math.round(hours)} h`;
  const totalDays = Math.round(hours / 24);
  const years = Math.floor(totalDays / 365);
  const months = Math.floor((totalDays % 365) / 30);
  const days = (totalDays % 365) % 30;
  const parts = [
    years ? `${years} ${years === 1 ? "year" : "years"}` : "",
    months ? `${months} ${months === 1 ? "month" : "months"}` : "",
    days ? `${days} ${days === 1 ? "day" : "days"}` : "",
  ].filter(Boolean);
  return parts.slice(0, 2).join(" ") || "0 days";
}

// forecastSeries only carries a single P50-ish trend value per point; the
// P10-P90 band is reconstructed here by widening proportionally from that
// trend using the prediction's scalar rulHoursP10/P90 spread, growing with
// forecast horizon (near-term is more certain than the 14-day-out tail).
// All series values are hours; the chart shows them in one unit chosen to suit the largest value.
function chartUnit(maxHours: number): { name: "days" | "months" | "years"; hours: number } {
  if (maxHours < 90 * 24) return { name: "days", hours: 24 };
  if (maxHours < 730 * 24) return { name: "months", hours: 30 * 24 };
  return { name: "years", hours: 365 * 24 };
}

const round1 = (v: number) => Math.round(v * 10) / 10;

function buildBandedSeries(prediction: Prediction, unitHours: number) {
  const n = prediction.forecastSeries.length;
  const p10Spread = prediction.rulHoursP50 - prediction.rulHoursP10;
  const p90Spread = prediction.rulHoursP90 - prediction.rulHoursP50;
  return prediction.forecastSeries.map((point, i) => {
    const horizonFactor = (i + 1) / n;
    const low = Math.max(0, point.value - p10Spread * horizonFactor * 0.4);
    const high = point.value + p90Spread * horizonFactor * 0.4;
    return {
      timestamp: point.timestamp,
      p50: round1(point.value / unitHours),
      band: [round1(low / unitHours), round1(high / unitHours)] as [number, number],
    };
  });
}

export function ForecastsRulPage() {
  const { turbineId = "" } = useParams();
  const [predictions, setPredictions] = useState<Prediction[] | null>(null);
  const [component, setComponent] = useState<string | null>(null);

  useEffect(() => {
    setPredictions(null);
    getPredictions(turbineId).then((preds) => {
      setPredictions(preds);
      setComponent(preds[0]?.component ?? null);
    });
  }, [turbineId]);

  const active = predictions?.find((p) => p.component === component) ?? null;
  const unit = useMemo(
    () => chartUnit(active ? Math.max(active.rulHoursP90, ...active.forecastSeries.map((p: { value: number }) => p.value)) : 0),
    [active],
  );
  const series = useMemo(() => (active ? buildBandedSeries(active, unit.hours) : []), [active, unit]);

  return (
    <div className="forecasts-rul">
      <header className="module-header">
        <h1>Forecasts &amp; RUL - {turbineId}</h1>
        <p className="module-subtitle">
          Remaining-useful-life forecast per component.
        </p>
      </header>

      {!predictions ? (
        <p>Loading predictions…</p>
      ) : (
        <>
          <div className="component-tabs">
            {predictions.map((p) => (
              <button
                key={p.component}
                className={p.component === component ? "tab active" : "tab"}
                onClick={() => setComponent(p.component)}
              >
                {p.component}
              </button>
            ))}
          </div>

          {active && (
            <>
              <section className="tile-row">
                <StatTile
                  label="RUL (P50)"
                  value={formatRul(active.rulHoursP50)}
                  sublabel={`P10 ${formatRul(active.rulHoursP10)} – P90 ${formatRul(active.rulHoursP90)}`}
                />
                <StatTile
                  label="Fault probability (30d)"
                  value={`${Math.round(active.faultProbability * 100)}%`}
                  accent={active.faultProbability > 0.25 ? HEALTH_COLORS.red : HEALTH_COLORS.green}
                />
                <StatTile label="Component" value={active.component} />
              </section>

              <section className="chart-card">
                <h2>RUL forecast with P10-P90 band</h2>
                <ResponsiveContainer width="100%" height={360}>
                  <ComposedChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis
                      dataKey="timestamp"
                      tick={{ fontSize: 11 }}
                      tickFormatter={(v: string) => new Date(v).toLocaleDateString()}
                    />
                    <YAxis
                      tick={{ fontSize: 12 }}
                      label={{ value: `RUL (${unit.name})`, angle: -90, position: "insideLeft", fontSize: 12 }}
                    />
                    <Tooltip
                      labelFormatter={(v: string) => new Date(v).toLocaleDateString()}
                      formatter={(value: number | [number, number]) =>
                        Array.isArray(value)
                          ? `${formatRul(value[0] * unit.hours)} – ${formatRul(value[1] * unit.hours)}`
                          : formatRul(value * unit.hours)
                      }
                      contentStyle={{ fontSize: 12 }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Area
                      dataKey="band"
                      name="P10-P90 band"
                      stroke="none"
                      fill="#3b6fa0"
                      fillOpacity={0.18}
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="p50"
                      name="P50 forecast"
                      stroke="#3b6fa0"
                      strokeWidth={2}
                      dot={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
