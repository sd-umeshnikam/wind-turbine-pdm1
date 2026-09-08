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
import { getTelemetry } from "../../api/client";
import type { SensorReading } from "../../api/types";
import type { HealthStatus } from "../../api/types";
import { HealthPill } from "../../shared/HealthPill";
import { colorForIndex } from "../../shared/theme";
import "./AssetDetailPage.css";

const COMPONENT_SENSOR: Record<string, string> = {
  Gearbox: "gearbox_oil_temp",
  Hydraulics: "hydraulic_oil_temp",
  "Pitch System": "pitch_motor_temp",
  Generator: "generator_bearing_temp",
  Transformer: "transformer_oil_temp",
  "Rotor Brake": "rotor_brake_pressure",
  Bearing: "bearing_vibration_rms",
};

function healthFromValues(values: number[]): HealthStatus {
  if (values.length === 0) return "green";
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const latest = values[values.length - 1];
  const delta = latest - mean;
  if (delta > 6) return "red";
  if (delta > 3) return "amber";
  return "green";
}

export function AssetDetailPage() {
  const { turbineId = "" } = useParams();
  const [readings, setReadings] = useState<SensorReading[] | null>(null);

  useEffect(() => {
    setReadings(null);
    const to = new Date();
    const from = new Date(to.getTime() - 48 * 3600_000);
    getTelemetry(turbineId, from.toISOString(), to.toISOString()).then(setReadings);
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

  const components = useMemo(() => {
    return Object.entries(COMPONENT_SENSOR).map(([name, sensor]) => {
      const values = (readings ?? [])
        .filter((r) => r.sensor === sensor)
        .map((r) => r.value);
      return { name, sensor, health: healthFromValues(values) };
    });
  }, [readings]);

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
        <h2>Sensor trend (last 48h, mock-backed until AppSync is live)</h2>
        {!readings ? (
          <p>Loading telemetry…</p>
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
        <ul>
          {components.map((c) => (
            <li key={c.name}>
              <span className="component-name">{c.name}</span>
              <span className="component-sensor">{c.sensor}</span>
              <HealthPill status={c.health} label={c.health} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
