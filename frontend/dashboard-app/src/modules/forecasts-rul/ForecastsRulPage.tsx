import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getPredictions } from "../../api/client";
import type { Prediction } from "../../api/types";
import { StatTile } from "../../shared/StatTile";
import { HEALTH_COLORS } from "../../shared/theme";
import { formatRul } from "../../shared/formatRul";
import { TurbineLoader } from "../../shared/TurbineLoader";
import "./ForecastsRulPage.css";

const HOUR_MS = 3600_000;
const DAY_MS = 24 * HOUR_MS;
const CHART_POINTS = 40;
// From the model QA (Farm A gearbox, 123,820 labelled readings): the RUL models were
// trained only on the 30 days (720 h) before past failures, and the real remaining life
// fell inside P10-P90 just 29% of the time. Shown to users so the band isn't read as precise.
const RUL_TRAINING_HORIZON_DAYS = 30;
const RUL_P10_P90_COVERAGE = "29%";
// A trend forecast that moves less than this over its whole horizon is a flat line.
const FLAT_TREND_RANGE = 0.01;
const LIVE_WINDOW_DAYS = 7;

function chartUnit(maxHours: number): { name: "days" | "months" | "years"; hours: number } {
  if (maxHours < 90 * 24) return { name: "days", hours: 24 };
  if (maxHours < 730 * 24) return { name: "months", hours: 30 * 24 };
  return { name: "years", hours: 365 * 24 };
}

const round1 = (v: number) => Math.round(v * 10) / 10;

const prettyComponent = (c: string) => {
  const s = c.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
};

// Remaining life counts down one hour per hour from the prediction until it hits zero,
// for the median (P50) and the P10-P90 range. It starts at the time of the data the
// prediction was made from (asOf), not today. Built from the model's RUL quantiles -
// not from forecastSeries, which is a health-index forecast (see below).
function buildRulCountdown(p: Prediction, unitHours: number, startMs: number) {
  const horizonHours = Math.max(p.rulHoursP90, 24);
  const step = horizonHours / CHART_POINTS;
  return Array.from({ length: CHART_POINTS + 1 }, (_, i) => {
    const elapsed = i * step;
    const left = (h: number) => round1(Math.max(0, h - elapsed) / unitHours);
    return {
      timestamp: new Date(startMs + elapsed * HOUR_MS).toISOString(),
      p50: left(p.rulHoursP50),
      band: [left(p.rulHoursP10), left(p.rulHoursP90)] as [number, number],
    };
  });
}

const dateLabel = (v: string) => new Date(v).toLocaleDateString([], { month: "short", day: "numeric" });

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
  const unit = useMemo(() => chartUnit(active?.rulHoursP90 ?? 0), [active]);
  const asOfMs = active?.asOf ? Date.parse(active.asOf) : Date.now();
  // Real-time data has a reading from the last week. Replayed dataset readings can be
  // years in the past or future (dates are anonymised per turbine), so calendar dates
  // would be meaningless: show time relative to the latest reading instead.
  const isLive = Math.abs(Date.now() - asOfMs) <= LIVE_WINDOW_DAYS * DAY_MS;
  const xLabel = (v: string) =>
    isLive ? dateLabel(v) : `+${Math.round((Date.parse(v) - asOfMs) / DAY_MS)}d`;
  const xTooltip = (v: string) =>
    isLive
      ? new Date(v).toLocaleDateString()
      : `${Math.round((Date.parse(v) - asOfMs) / DAY_MS)} days after latest reading`;
  const countdown = useMemo(
    () => (active ? buildRulCountdown(active, unit.hours, asOfMs) : []),
    [active, unit, asOfMs],
  );
  const planBy = active ? new Date(asOfMs + active.rulHoursP10 * HOUR_MS) : null;
  const health = useMemo(
    () => (active?.forecastSeries ?? []).map((pt) => ({ timestamp: pt.timestamp, value: Math.round(pt.value * 100) / 100 })),
    [active],
  );
  const healthValues = health.map((h) => h.value);
  const healthIsFlat = health.length > 0 && Math.max(...healthValues) - Math.min(...healthValues) < FLAT_TREND_RANGE;
  const fmtDate = (ms: number) => new Date(ms).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });

  return (
    <div className="forecasts-rul">
      <header className="module-header">
        <h1>Forecasts &amp; RUL - {turbineId}</h1>
        <p className="module-subtitle">Remaining life by component.</p>
      </header>

      {!predictions ? (
        <TurbineLoader label="Loading predictions…" />
      ) : predictions.length === 0 ? (
        <div className="card empty-state">No predictions for this turbine.</div>
      ) : (
        <>
          <div className="tabs" role="tablist" aria-label="Component">
            {predictions.map((p) => (
              <button
                key={p.component}
                type="button"
                role="tab"
                aria-selected={p.component === component}
                className={p.component === component ? "tab active" : "tab"}
                onClick={() => setComponent(p.component)}
              >
                {prettyComponent(p.component)}
              </button>
            ))}
          </div>

          {active && (
            <>
              <section className="tile-row">
                <StatTile
                  label="Remaining life (P50)"
                  value={formatRul(active.rulHoursP50)}
                  sublabel={`Range ${formatRul(active.rulHoursP10)} – ${formatRul(active.rulHoursP90)}`}
                />
                {isLive ? (
                  <StatTile
                    label="Plan maintenance by"
                    value={planBy ? fmtDate(planBy.getTime()) : "-"}
                    sublabel="Based on P10"
                  />
                ) : (
                  <StatTile
                    label="Plan maintenance within"
                    value={formatRul(active.rulHoursP10)}
                    sublabel="Based on P10"
                  />
                )}
                <StatTile
                  label="Fault probability"
                  value={`${Math.round(active.faultProbability * 100)}%`}
                  accent={active.faultProbability > 0.25 ? HEALTH_COLORS.red : HEALTH_COLORS.green}
                  sublabel={active.faultProbability > 0.25 ? "Elevated risk" : "Low risk"}
                />
              </section>

              <section className="chart-card">
                <h2>Remaining life</h2>
                <p className="chart-caveat">
                  Early warning only. Covers up to {RUL_TRAINING_HORIZON_DAYS} days; band accuracy in testing:{" "}
                  {RUL_P10_P90_COVERAGE}.
                </p>
                <ResponsiveContainer width="100%" height={340}>
                  <ComposedChart data={countdown} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="timestamp" tick={{ fontSize: 11 }} tickFormatter={xLabel} minTickGap={24} />
                    <YAxis
                      tick={{ fontSize: 12 }}
                      label={{ value: `Remaining life (${unit.name})`, angle: -90, position: "insideLeft", fontSize: 12 }}
                    />
                    <Tooltip
                      labelFormatter={xTooltip}
                      formatter={(value: number | [number, number]) =>
                        Array.isArray(value)
                          ? `${formatRul(value[0] * unit.hours)} – ${formatRul(value[1] * unit.hours)}`
                          : formatRul(value * unit.hours)
                      }
                      contentStyle={{ fontSize: 12 }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {planBy && (
                      <ReferenceLine
                        x={countdown.find((pt) => pt.band[0] === 0)?.timestamp}
                        stroke={HEALTH_COLORS.amber}
                        strokeDasharray="4 4"
                        label={{ value: "Plan by", position: "insideTopRight", fontSize: 11, fill: HEALTH_COLORS.amber }}
                      />
                    )}
                    <Area
                      dataKey="band"
                      name="P10–P90 range"
                      stroke="none"
                      fill="var(--chart-1)"
                      fillOpacity={0.18}
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="p50"
                      name="Most likely (P50)"
                      stroke="var(--chart-1)"
                      strokeWidth={2.5}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </section>

              {healthIsFlat && (
                <section className="card">
                  <h2>Health trend</h2>
                  <p className="chart-help" style={{ margin: 0 }}>
                    No reliable forecast available.
                  </p>
                </section>
              )}

              {health.length > 0 && !healthIsFlat && (
                <section className="chart-card">
                  <h2>Health trend (next {health.length} days)</h2>
                  <p className="chart-help">Higher is healthier.</p>
                  <ResponsiveContainer width="100%" height={240}>
                    <LineChart data={health} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="timestamp" tick={{ fontSize: 11 }} tickFormatter={xLabel} minTickGap={24} />
                      <YAxis
                        tick={{ fontSize: 12 }}
                        domain={["auto", "auto"]}
                        label={{ value: "Health score", angle: -90, position: "insideLeft", fontSize: 12 }}
                      />
                      <Tooltip labelFormatter={xTooltip} contentStyle={{ fontSize: 12 }} />
                      <Line
                        dataKey="value"
                        name="Health score"
                        stroke={HEALTH_COLORS.green}
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </section>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
