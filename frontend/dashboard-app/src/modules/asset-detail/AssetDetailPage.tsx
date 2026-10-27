import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getPredictions, getTelemetry } from "../../api/client";
import type { HealthStatus, Prediction, SensorReading } from "../../api/types";
import { Badge, HealthPill } from "../../shared/HealthPill";
import { colorForIndex } from "../../shared/theme";
import { formatRul } from "../../shared/formatRul";
import { TurbineLoader } from "../../shared/TurbineLoader";
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
const DEFAULT_SENSORS_SHOWN = 6;

// Mirrors the alerting service: a short remaining life only counts as serious when the
// fault classifier also sees risk, so one unreliable model can't turn a part red.
const CORROBORATION_PROBABILITY = 0.25;
const ALERT_RUL_HOURS = 72;

function healthFromPrediction(p: Prediction): { status: HealthStatus; note: string } {
  const corroborated = p.faultProbability >= CORROBORATION_PROBABILITY;
  const detail = `Fault ${Math.round(p.faultProbability * 100)}% · ${formatRul(p.rulHoursP50)} left`;
  if (p.faultProbability > 0.8 || (corroborated && p.rulHoursP50 < 48)) return { status: "red", note: detail };
  if (corroborated) return { status: "amber", note: detail };
  if (p.rulHoursP50 < ALERT_RUL_HOURS) {
    return { status: "amber", note: `${detail} · check` };
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
    const sensorNames = Array.from(new Set(readings.map((r) => r.sensor))).sort((a, b) =>
      a.localeCompare(b, undefined, { numeric: true }),
    );
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

  // Real turbines have up to ~80 anonymised sensors; plotting them all at once is
  // unreadable, so start with a handful and let the user pick.
  const [selected, setSelected] = useState<string[] | null>(null);
  useEffect(() => setSelected(null), [turbineId]);
  const shown = selected ?? sensors.slice(0, DEFAULT_SENSORS_SHOWN);
  const toggleSensor = (s: string) =>
    setSelected((cur) => {
      const base = cur ?? sensors.slice(0, DEFAULT_SENSORS_SHOWN);
      return base.includes(s) ? base.filter((x) => x !== s) : [...base, s];
    });

  const components = useMemo(
    () =>
      COMPONENTS.map(({ name, keys }) => {
        const p = predictions?.find((x) => keys.includes(normalize(x.component)));
        return { name, ...(p ? healthFromPrediction(p) : { status: null, note: "No prediction" }) };
      }),
    [predictions],
  );

  return (
    <div className="asset-detail">
      <header className="module-header">
        <h1>Turbine {turbineId}</h1>
      </header>

      <section className="card component-list">
        <h2>Components</h2>
        {!predictions ? (
          <TurbineLoader label="Loading predictions…" />
        ) : (
          <ul>
            {components.map((c) => (
              <li key={c.name}>
                <span className="component-name">{c.name}</span>
                <span className="component-sensor">{c.note}</span>
                {c.status ? (
                  <HealthPill status={c.status} label={STATUS_LABEL[c.status]} />
                ) : (
                  <Badge tone="neutral">No data</Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="chart-card">
        <div className="chart-toolbar">
          <h2>Sensor trend</h2>
          {sensors.length > 0 && (
            <p>
              {shown.length} of {sensors.length} sensors
            </p>
          )}
        </div>
        {!readings ? (
          <TurbineLoader label="Loading sensor data…" />
        ) : readings.length === 0 ? (
          <p className="empty-state">No sensor data.</p>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="timestamp"
                  tick={{ fontSize: 11 }}
                  minTickGap={32}
                  tickFormatter={(v: string) => new Date(v).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                />
                <YAxis tick={{ fontSize: 12 }} width={56} />
                <Tooltip labelFormatter={(v: string) => new Date(v).toLocaleString()} contentStyle={{ fontSize: 12 }} />
                {shown.map((sensor) => (
                  <Line
                    key={sensor}
                    type="monotone"
                    dataKey={sensor}
                    stroke={colorForIndex(sensors.indexOf(sensor))}
                    dot={false}
                    strokeWidth={2}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
            <div className="sensor-picker" role="group" aria-label="Sensors to plot">
              {sensors.map((s, i) => (
                <button
                  key={s}
                  type="button"
                  className="sensor-chip"
                  aria-pressed={shown.includes(s)}
                  onClick={() => toggleSensor(s)}
                >
                  <span className="dot" style={{ background: shown.includes(s) ? colorForIndex(i) : "var(--border-strong)" }} />
                  {s.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
