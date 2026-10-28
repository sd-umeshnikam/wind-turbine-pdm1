import { AlertOctagon, BellRing, Gauge, HeartPulse, Wind } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAlerts, useFarms, useFleet } from "../api/hooks";
import { useActivity } from "../api/stream";
import type { AuditEntry, Fleet, TurbineSummary } from "../api/types";
import { InsightsList } from "../assistant/Insights";
import { Card, Empty, HealthBadge, Kpi, PageHead, QueryView, Segmented, SeverityBadge, StatusBadge } from "../components/ui";
import { ago, dataTime, int, num, titleCase } from "../lib/format";
import { BAND_LABEL, band } from "../lib/health";

// Display order of components in the heatmap (drive train first).
const COMPONENT_ORDER = [
  "rotor",
  "pitch",
  "gearbox",
  "generator",
  "converter",
  "transformer",
  "electrical",
  "hydraulics",
  "yaw",
  "rotor_brake",
  "nacelle",
  "tower",
];

function componentsOf(turbines: TurbineSummary[]): string[] {
  const seen = new Set(turbines.flatMap((t) => Object.keys(t.components)));
  return [...COMPONENT_ORDER.filter((c) => seen.has(c)), ...[...seen].filter((c) => !COMPONENT_ORDER.includes(c)).sort()];
}

function HealthHeatmap({ turbines }: { turbines: TurbineSummary[] }) {
  const navigate = useNavigate();
  const components = useMemo(() => componentsOf(turbines), [turbines]);
  const sorted = useMemo(
    () => [...turbines].sort((a, b) => (a.health ?? 101) - (b.health ?? 101) || a.id.localeCompare(b.id)),
    [turbines],
  );
  if (!turbines.length) return <Empty title="No turbines in this selection" />;
  return (
    <div className="table-wrap" style={{ padding: "8px 12px 12px" }}>
      <table className="heatmap">
        <caption className="sr-only">Health of each component per turbine, worst turbine first</caption>
        <thead>
          <tr>
            <th scope="col">Turbine</th>
            <th scope="col" className="col">
              Overall
            </th>
            {components.map((c) => (
              <th key={c} scope="col" className="col">
                {titleCase(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((t) => (
            <tr key={t.id}>
              <th scope="row">
                <Link to={`/turbines/${t.id}`}>{t.id}</Link>
                {t.active_alert && (
                  <span title={`Active ${t.active_alert.severity} alert`} style={{ marginLeft: 6 }}>
                    <BellRing size={12} aria-label="active alert" style={{ verticalAlign: -1, color: "var(--status-critical)" }} />
                  </span>
                )}
              </th>
              <HeatCell value={t.health} label={`${t.id} overall`} onClick={() => navigate(`/turbines/${t.id}`)} />
              {components.map((c) => (
                <HeatCell
                  key={c}
                  value={t.components[c]}
                  label={`${t.id} ${titleCase(c)}`}
                  onClick={() => navigate(`/turbines/${t.id}?component=${c}`)}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="legend" style={{ marginTop: 10 }}>
        <span>Health (0–100, 50 = alarm level):</span>
        <span><span className="swatch cell-good" />≥ 80 {BAND_LABEL.good}</span>
        <span><span className="swatch cell-watch" />65–80 {BAND_LABEL.watch}</span>
        <span><span className="swatch cell-degraded" />50–65 {BAND_LABEL.degraded}</span>
        <span><span className="swatch cell-alarm" />&lt; 50 {BAND_LABEL.alarm}</span>
        <span><span className="swatch" style={{ background: "var(--surface-2)" }} />not monitored on this farm</span>
      </div>
    </div>
  );
}

function HeatCell({ value, label, onClick }: { value: number | null | undefined; label: string; onClick: () => void }) {
  if (value === undefined || value === null) {
    return (
      <td className="cell na" title={`${label}: no score`}>
        –
      </td>
    );
  }
  const b = band(value);
  return (
    <td
      className={`cell cell-${b}`}
      title={`${label}: ${num(value)} (${BAND_LABEL[b]})`}
      onClick={onClick}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      tabIndex={0}
    >
      {Math.round(value)}
    </td>
  );
}

function KpiStrip({ fleet }: { fleet: Fleet }) {
  const k = fleet.kpis;
  const active = Object.values(k.active_alerts).reduce((a, b) => a + b, 0);
  return (
    <div className="kpis">
      <Kpi
        icon={<Wind size={14} />}
        label="Turbines reporting"
        value={`${k.reporting} / ${k.turbines}`}
        foot="health score at the replay cursor"
      />
      <Kpi icon={<HeartPulse size={14} />} label="Mean turbine health" value={num(k.mean_health)} foot="calibrated 0–100" />
      <Kpi
        icon={<AlertOctagon size={14} />}
        label="Turbines in alarm"
        value={k.in_alarm}
        foot="detector above its alarm threshold"
      />
      <Kpi
        icon={<BellRing size={14} />}
        label="Active alerts"
        value={active}
        foot={`${k.active_alerts.critical} critical · ${k.active_alerts.high} high · ${k.unacknowledged} unacknowledged`}
      />
      <Kpi
        icon={<Gauge size={14} />}
        label="Replay speed"
        value={`${fleet.replay_speed.toLocaleString()}×`}
        foot="data seconds per wall-clock second"
      />
    </div>
  );
}

function describe(a: AuditEntry): string {
  const d = a.details ?? {};
  const turbine = typeof d.turbine === "string" ? ` on ${d.turbine}` : "";
  const verb = a.action.split(".").slice(1).join(" ").replace(/_/g, " ");
  return `${titleCase(a.entity)} ${verb}${turbine}`;
}

function ActivityFeed() {
  const activity = useActivity();
  if (!activity.length)
    return (
      <Empty title="No changes yet">
        Alert, model and retraining events appear here as they happen while the console is open.
      </Empty>
    );
  return (
    <ul className="feed" aria-live="polite">
      {activity.slice(0, 12).map((a) => (
        <li key={a.id}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 500 }}>
              {a.entity === "alert" && a.entity_id ? <Link to={`/alerts?id=${a.entity_id}`}>{describe(a)}</Link> : describe(a)}
            </div>
            <div className="subtle">
              {a.actor} · {ago(a.ts)}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function LatestAlerts() {
  const alerts = useAlerts({ active: true, sort: "-updated_at", limit: 6 });
  return (
    <QueryView query={alerts} height={200}>
      {(page) =>
        page.items.length ? (
          <ul className="feed">
            {page.items.map((a) => (
              <li key={a.id}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="row" style={{ gap: 6 }}>
                    <SeverityBadge severity={a.severity} />
                    <StatusBadge status={a.status} />
                  </div>
                  <div style={{ marginTop: 4 }}>
                    <Link to={`/alerts?id=${a.id}`}>{a.title}</Link>
                  </div>
                  <div className="subtle">
                    data time {dataTime(a.last_data_ts ?? a.data_ts)} · updated {ago(a.updated_at)}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="No active alerts">Every turbine is within its normal behaviour.</Empty>
        )
      }
    </QueryView>
  );
}

function FarmCards() {
  const farms = useFarms();
  return (
    <QueryView query={farms} height={140}>
      {(list) => (
        <div className="grid cols-3">
          {list.map((f) => (
            <div key={f.id} className="card" style={{ padding: 16 }}>
              <div className="row">
                <h2 style={{ flex: 1 }}>{f.name}</h2>
                {f.active_alerts > 0 ? (
                  <span className="badge critical">{f.active_alerts} active alerts</span>
                ) : (
                  <span className="badge good">No active alerts</span>
                )}
              </div>
              <div className="subtle" style={{ marginBottom: 10 }}>
                {f.description}
              </div>
              <dl className="kv">
                <dt>Turbines</dt>
                <dd>{f.turbines}</dd>
                <dt>SCADA signals</dt>
                <dd>{int(f.sensors)}</dd>
                <dt>Labelled events</dt>
                <dd>
                  {f.events.anomaly ?? 0} anomaly · {f.events.normal ?? 0} normal
                </dd>
                <dt>Champion model</dt>
                <dd>{f.champion ? <Link to={`/models?farm=${f.id}`}>{f.champion}</Link> : "none"}</dd>
              </dl>
            </div>
          ))}
        </div>
      )}
    </QueryView>
  );
}

export function FleetPage() {
  const [farm, setFarm] = useState<string>("all");
  const fleet = useFleet(farm === "all" ? undefined : farm);
  const worst = fleet.data?.turbines
    .filter((t) => t.health !== null)
    .sort((a, b) => (a.health ?? 0) - (b.health ?? 0))[0];

  return (
    <>
      <PageHead
        title="Fleet overview"
        lede="Condition of every turbine and component at its current replay position, from the champion health model of each farm."
        actions={
          <Segmented
            label="Farm"
            value={farm}
            onChange={setFarm}
            options={[
              { value: "all", label: "All farms" },
              { value: "A", label: "Farm A" },
              { value: "B", label: "Farm B" },
              { value: "C", label: "Farm C" },
            ]}
          />
        }
      />
      <QueryView query={fleet} height={96}>
        {(f) => <KpiStrip fleet={f} />}
      </QueryView>
      <div className="grid cols-main-side" style={{ marginBottom: 16 }}>
        <Card
          title="Component health by turbine"
          hint={worst ? <>Lowest: {worst.id} <HealthBadge health={worst.health} /></> : undefined}
          flush
        >
          <QueryView query={fleet} height={420}>
            {(f) => <HealthHeatmap turbines={f.turbines} />}
          </QueryView>
        </Card>
        <div className="stack">
          <Card title="What's new" hint="from the audit log and live state">
            <InsightsList />
          </Card>
          <Card title="Latest active alerts" flush tools={<Link to="/alerts">Work queue →</Link>}>
            <LatestAlerts />
          </Card>
          <Card title="Live activity" hint="since this page opened" flush>
            <ActivityFeed />
          </Card>
        </div>
      </div>
      <FarmCards />
    </>
  );
}
