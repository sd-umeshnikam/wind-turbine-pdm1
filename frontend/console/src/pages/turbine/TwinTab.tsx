// Digital twin: a schematic of the turbine driven entirely by replayed SCADA readings
// (rotor speed, pitch angle, wind speed, power, temperatures) and live component health.
// A quantity the farm does not measure is shown as "not measured", never estimated.

import { useMemo } from "react";
import { useSnapshot } from "../../api/hooks";
import type { ConditionReading, TurbineDetail } from "../../api/types";
import { Card, Empty, ErrorState, HealthBadge, Loading } from "../../components/ui";
import { dataTime, num, titleCase, withUnit } from "../../lib/format";
import { BAND_LABEL, band, type Band } from "../../lib/health";

/** Pick the reading of a kind whose description best matches (e.g. the rotor, not the generator). */
export function pickReading(
  readings: ConditionReading[],
  kind: string,
  prefer?: RegExp,
  avoid?: RegExp,
): ConditionReading | undefined {
  const of = readings.filter((r) => r.kind === kind && r.value !== null);
  return (
    of.find((r) => prefer?.test(r.description) && !avoid?.test(r.description)) ??
    (prefer ? undefined : of.find((r) => !avoid?.test(r.description)) ?? of[0])
  );
}

const BAND_FILL: Record<Band, string> = {
  good: "var(--status-good-soft)",
  watch: "var(--status-warning-soft)",
  degraded: "var(--status-serious-soft)",
  alarm: "var(--status-critical-soft)",
  none: "var(--surface-2)",
};
const BAND_STROKE: Record<Band, string> = {
  good: "var(--status-good)",
  watch: "var(--status-warning)",
  degraded: "var(--status-serious)",
  alarm: "var(--status-critical)",
  none: "var(--border-strong)",
};

// Nacelle schematic: drive train left to right, auxiliaries below.
const LAYOUT: { code: string; x: number; y: number; w: number; h: number }[] = [
  { code: "pitch", x: 10, y: 70, w: 80, h: 90 },
  { code: "rotor", x: 100, y: 70, w: 80, h: 90 },
  { code: "gearbox", x: 190, y: 60, w: 110, h: 110 },
  { code: "generator", x: 310, y: 70, w: 100, h: 90 },
  { code: "converter", x: 420, y: 70, w: 90, h: 90 },
  { code: "transformer", x: 520, y: 70, w: 90, h: 90 },
  { code: "hydraulics", x: 100, y: 190, w: 110, h: 76 },
  { code: "rotor_brake", x: 220, y: 190, w: 110, h: 76 },
  { code: "yaw", x: 340, y: 190, w: 110, h: 76 },
  { code: "electrical", x: 460, y: 190, w: 150, h: 76 },
];

function Rotor({ rpm }: { rpm: number | null }) {
  const spinning = rpm !== null && rpm > 0.5;
  const blade = "M0,-6 L4,-140 Q0,-150 -4,-140 Z";
  return (
    <svg viewBox="0 0 300 400" style={{ width: "100%", maxHeight: 420 }} role="img" aria-label="Rotor and tower">
      <defs>
        <linearGradient id="tower" x1="0" x2="1">
          <stop offset="0" stopColor="var(--surface-3)" />
          <stop offset="1" stopColor="var(--surface-2)" />
        </linearGradient>
      </defs>
      <path d="M140 165 L132 395 L168 395 L160 165 Z" fill="url(#tower)" stroke="var(--border-strong)" />
      <rect x="128" y="150" width="44" height="26" rx="8" fill="var(--surface-3)" stroke="var(--border-strong)" />
      <g transform="translate(150 160)">
        <g
          className="twin-rotor"
          style={{
            animation: spinning ? `twin-spin ${(60 / (rpm ?? 1)).toFixed(2)}s linear infinite` : undefined,
            transformOrigin: "0 0",
          }}
        >
          {[0, 120, 240].map((a) => (
            <g key={a} transform={`rotate(${a})`}>
              <path d={blade} fill="var(--surface-1)" stroke="var(--ink-3)" strokeWidth="1.2" />
            </g>
          ))}
        </g>
        <circle r="11" fill="var(--accent)" />
      </g>
    </svg>
  );
}

function Nacelle({ turbine, onComponent }: { turbine: TurbineDetail; onComponent: (c: string) => void }) {
  return (
    <svg viewBox="0 0 620 276" style={{ width: "100%" }} role="img" aria-label="Nacelle components coloured by health">
      <rect x="2" y="40" width="616" height="140" rx="18" fill="none" stroke="var(--border-strong)" strokeDasharray="4 4" />
      <text x="12" y="30" fontSize="12" fill="var(--ink-3)">
        Nacelle drive train
      </text>
      {LAYOUT.map((box) => {
        const health = turbine.components[box.code];
        const b = band(health);
        const monitored = health !== undefined;
        return (
          <g
            key={box.code}
            role="button"
            tabIndex={monitored ? 0 : -1}
            aria-label={`${titleCase(box.code)}: ${monitored ? `${num(health, 0)} ${BAND_LABEL[b]}` : "not monitored"}`}
            style={{ cursor: monitored ? "pointer" : "default" }}
            onClick={() => monitored && onComponent(box.code)}
            onKeyDown={(e) => monitored && e.key === "Enter" && onComponent(box.code)}
          >
            <rect
              x={box.x}
              y={box.y}
              width={box.w}
              height={box.h}
              rx="8"
              fill={BAND_FILL[monitored ? b : "none"]}
              stroke={BAND_STROKE[monitored ? b : "none"]}
              strokeWidth={b === "alarm" ? 2.5 : 1.5}
            />
            <text x={box.x + 8} y={box.y + 20} fontSize="12" fontWeight="600" fill="var(--ink-1)">
              {titleCase(box.code)}
            </text>
            <text x={box.x + 8} y={box.y + 42} fontSize="18" fontWeight="600" fill="var(--ink-1)">
              {monitored ? num(health, 0) : "–"}
            </text>
            <text x={box.x + 8} y={box.y + 58} fontSize="11" fill="var(--ink-2)">
              {monitored ? BAND_LABEL[b] : "not monitored"}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Reading({ label, reading, missing = "not measured" }: { label: string; reading?: ConditionReading; missing?: string }) {
  return (
    <div className="card kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={{ fontSize: 22 }}>
        {reading ? withUnit(reading.value, reading.unit) : <span className="subtle">{missing}</span>}
      </div>
      <div className="kpi-foot">{reading ? reading.description : " "}</div>
    </div>
  );
}

export function TwinTab({ turbine, onComponent }: { turbine: TurbineDetail; onComponent: (c: string) => void }) {
  const snap = useSnapshot(turbine.id);
  const r = useMemo(() => {
    const readings = snap.data?.readings ?? [];
    return {
      power: pickReading(readings, "power", /active power|positive active|grid/i),
      wind: pickReading(readings, "wind_speed"),
      rotor: pickReading(readings, "rotor_speed", /rotor/i, /generator|gearbox|converter/i),
      pitch: pickReading(readings, "pitch_angle"),
      ambient: pickReading(readings, "ambient_temp"),
      nacelle: pickReading(readings, "nacelle_temp"),
    };
  }, [snap.data]);

  if (snap.isLoading) return <Loading height={420} />;
  if (snap.error && !snap.data) return <ErrorState error={snap.error} retry={() => void snap.refetch()} />;
  if (!snap.data?.cursor_ts) return <Card><Empty title="The replay has not reached this turbine yet" /></Card>;

  return (
    <div className="stack">
      <div className="kpis" style={{ marginBottom: 0 }}>
        <Reading label="Active power" reading={r.power} />
        <Reading label="Wind speed" reading={r.wind} />
        <Reading label="Rotor speed" reading={r.rotor} missing="not measured on this farm" />
        <Reading label="Pitch angle" reading={r.pitch} />
        <Reading label="Ambient temperature" reading={r.ambient} />
        <Reading label="Nacelle temperature" reading={r.nacelle} />
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 320px) minmax(0, 1fr)" }}>
        <Card title="Rotor" hint={r.rotor ? `spinning at the replayed ${num(r.rotor.value)} rpm` : "static: rotor speed is not measured"}>
          <Rotor rpm={r.rotor?.value ?? null} />
        </Card>
        <Card
          title="Component condition"
          hint="click a component for its sub-parts"
          tools={<HealthBadge health={turbine.health} />}
        >
          <Nacelle turbine={turbine} onComponent={onComponent} />
          <dl className="kv" style={{ marginTop: 12 }}>
            <dt>Data time</dt>
            <dd>{dataTime(snap.data.cursor_ts)}</dd>
            <dt>Operating state</dt>
            <dd>{snap.data.operating_status_label ?? "not reported"}</dd>
            <dt>Weakest sub-part</dt>
            <dd>{turbine.worst_subcomponent ?? "—"}</dd>
            <dt>Source</dt>
            <dd>Replay of recorded SCADA history, refreshed every 10 s</dd>
          </dl>
        </Card>
      </div>
    </div>
  );
}
