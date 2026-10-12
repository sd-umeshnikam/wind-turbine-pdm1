import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getPredictions, getTelemetry } from "../../api/client";
import type { HealthStatus, Prediction, SensorReading } from "../../api/types";
import { HealthPill } from "../../shared/HealthPill";
import { colorForIndex } from "../../shared/theme";
import { formatRul } from "../../shared/formatRul";
import { STATUS_LABEL } from "../digital-twin/twinText";
import "./AssetDetailPage.css";

// Display name -> prediction component names. Mock data uses display names; the real
// inference server uses model names (e.g. "pitch", "rotor_brake", "vibration").
const COMPONENTS: { name: string; keys: string[] }[] = [
  { name: "Gearbox", keys: ["gearbox"] },
  { name: "Hydraulics", keys: ["hydraulics"] },
  { name: "Pitch System", keys: ["pitchsystem", "pitch"] },
  { name: "Generator", keys: ["generator"] },
  { name: "Transformer", keys: ["transformer"] },
  { name: "Rotor Brake", keys: ["rotorbrake"] },
  { name: "Bearing", keys: ["bearing", "vibration"] },
];

const normalize = (s: string) => s.toLowerCase().replace(/[^a-z]/g, "");

// Mirrors the alerting service: a short remaining life only counts as serious when the
// fault classifier also sees risk, so one unreliable model can't turn a part red.
const CORROBORATION_PROBABILITY = 0.25;
const ALERT_RUL_HOURS = 72;

function healthFromPrediction(p: Prediction): { status: HealthStatus; note: string } {
  const corroborated = p.faultProbability >= CORROBORATION_PROBABILITY;
  const detail = `Fault ${Math.round(p.faultProbability * 100)}% · Remaining life ${formatRul(p.rulHoursP50)}`;
  if (p.faultProbability > 0.8 || (corroborated && p.rulHoursP50 < 48)) return { status: "red", note: detail };
  if (corroborated) return { status: "amber", note: detail };
  if (p.rulHoursP50 < ALERT_RUL_HOURS) {
    return { status: "amber", note: `${detail} · short life predicted but fault risk is low, verify` };
  }
  return { status: "green", note: detail };
}

export function AssetDetailPage() {
  const { turbineId = "" } = useParams();
  const [readings, setReadings] = useState<SensorReading[] | null>(null);
  const [predictions, setPredictions] = useState<Prediction[] | null>(null);

  useEffect(() => {
    setReadings(null);
    setPredictions(null);
    const to = new Date();
    const from = new Date(to.getTime() - 48 * 3600_000);
    getTelemetry(turbineId, from.toISOString(), to.toISOString()).then(setReadings);
    getPredictions(turbineId)
      .then(setPredictions)
      .catch(() => setPredictions([]));
  }, [turbineId]);

  const { series, sensors } = useMemo(() => {
    if (!readings) return { series: [], sensors: [] as string[] };
    const sensorNames = Array.from(new Set(readings.map((r) => r.sensor)));
    const byTimestamp = new Map<string, Record<string, string | number>>();
    for (const r of readings) {
      const row = byTimestamp.get(r.timestamp) ?? { timestamp: r.timestamp };
      row[r.sensor] = r.value;
      byTimestamp.set(r.timestamp, row);
    }
    const rows = Array.from(byTimestamp.values()).sort((a, b) =>
      String(a.timestamp).localeCompare(String(b.timestamp)),
    );
    return { series: rows, sensors: sensorNames };
  }, [readings]);

  const components = useMemo(
    () =>
      COMPONENTS.map(({ name, keys }) => {
        const p = predictions?.find((x) => keys.includes(normalize(x.component)));
        return { name, ...(p ? healthFromPrediction(p) : { status: null, note: "No prediction available for this component" }) };
      }),
    [predictions],
  );

  return (
    <div className="asset-detail">
      <header className="module-header">
        <h1>Asset Detail - {turbineId}</h1>
        <p className="module-subtitle">
          Sensor trends and component health snapshot. Related views:{" "}
          <Link to={`/twin/${turbineId}`}>Digital twin</Link> ·{" "}
          <Link to={`/forecasts/${turbineId}`}>Forecasts / RUL</Link>
        </p>
      </header>

      <section className="chart-card">
        <h2>Sensor trend (last 48h of this turbine's data)</h2>
        {!readings ? (
          <p>Loading telemetry…</p>
        ) : readings.length === 0 ? (
          <p>No telemetry data available for this turbine.</p>
        ) : (
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="timestamp"
                tick={{ fontSize: 11 }}
                tickFormatter={(v: string) => new Date(v).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              />
              <YAxis
                tick={{ fontSize: 12 }}
                label={{ value: "Sensor value (mixed units - see legend/tooltip)", angle: -90, position: "insideLeft", fontSize: 11 }}
              />
              <Tooltip
                labelFormatter={(v: string) => new Date(v).toLocaleString()}
                contentStyle={{ fontSize: 12 }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {sensors.map((sensor, i) => (
                <Line
                  key={sensor}
                  type="monotone"
                  dataKey={sensor}
                  stroke={colorForIndex(i)}
                  dot={false}
                  strokeWidth={2}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </section>

      <section className="component-list">
        <h2>Components</h2>
        <p className="component-help">Health from the latest model predictions (fault probability and remaining life).</p>
        {!predictions ? (
          <p>Loading predictions…</p>
        ) : (
          <ul>
            {components.map((c) => (
              <li key={c.name}>
                <span className="component-name">{c.name}</span>
                <span className="component-sensor">{c.note}</span>
                {c.status ? (
                  <HealthPill status={c.status} label={STATUS_LABEL[c.status]} />
                ) : (
                  <span className="health-pill no-data">No data</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
