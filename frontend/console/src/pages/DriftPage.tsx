import { CheckCircle2, CircleHelp, RefreshCcw, TriangleAlert } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useDrift, useDriftHistory, useDriftPolicy, useRequestRetrain, useRetrainJobs, useRetrainSchedule } from "../api/hooks";
import type { DriftHistory, DriftSnapshot, DriftStatus, RetrainJob } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Chart, timeFrame, type ChartColors } from "../components/Chart";
import { useToast } from "../components/Toasts";
import { Badge, Card, Dialog, Empty, PageHead, QueryView } from "../components/ui";
import { ago, duration, num, titleCase, wallTime } from "../lib/format";

const STATUS: Record<DriftStatus, [string, string, JSX.Element]> = {
  ok: ["good", "No drift", <CheckCircle2 size={14} key="ok" />],
  warning: ["warning", "Informational breach", <TriangleAlert size={14} key="w" />],
  drift: ["critical", "Drift: retrain triggered", <TriangleAlert size={14} key="d" />],
  no_data: ["neutral", "Not checked yet", <CircleHelp size={14} key="n" />],
};

const DRIFT_METRICS: Record<string, string> = {
  psi_input: "Input distribution shift (PSI)",
  out_of_support: "Inputs outside the training range",
  residual_shift: "Residual / score shift",
  alert_rate: "Alert rate",
};

function StatusBadgeDrift({ status }: { status: DriftStatus }) {
  const [tone, label, icon] = STATUS[status];
  return (
    <Badge tone={tone}>
      {icon}
      {label}
    </Badge>
  );
}

function FarmDrift({ snap, selected, onSelect }: { snap: DriftSnapshot; selected: boolean; onSelect: () => void }) {
  const breached = snap.rows.filter((r) => r.breached).length;
  return (
    <button
      className="card"
      onClick={onSelect}
      style={{
        textAlign: "left",
        padding: 16,
        cursor: "pointer",
        outline: selected ? "2px solid var(--focus)" : undefined,
        background: "var(--surface-1)",
      }}
      aria-pressed={selected}
    >
      <div className="row">
        <h2 style={{ flex: 1 }}>Farm {snap.farm_id}</h2>
        <StatusBadgeDrift status={snap.status} />
      </div>
      <div className="subtle" style={{ marginTop: 6 }}>
        {snap.checked_at ? `checked ${ago(snap.checked_at)}` : "no drift check yet"} · {snap.rows.length} metrics ·{" "}
        {breached} breached
      </div>
    </button>
  );
}

function historyOption(h: DriftHistory) {
  return (c: ChartColors) => {
    const entries = Object.entries(h.series).slice(0, 8);
    const threshold = entries[0]?.[1][0]?.threshold;
    // Axis from zero up to past the threshold: a value's distance from the limit is the point.
    const peak = Math.max(threshold ?? 0, ...entries.flatMap(([, points]) => points.map((p) => p.value)));
    return {
      ...timeFrame(c, { legend: entries.length > 1, yMin: 0, yMax: Number((peak * 1.15).toPrecision(2)) }),
      series: entries.map(([name, points], i) => ({
        name,
        type: "line",
        showSymbol: points.length < 40,
        symbolSize: 8,
        color: c.series[i % c.series.length],
        lineStyle: { width: 2 },
        data: points.map((p) => [p.ts, p.value]),
        markLine:
          i === 0 && threshold !== undefined
            ? {
                silent: true,
                symbol: "none",
                lineStyle: { color: c.critical, type: "dashed", width: 1 },
                label: { formatter: "threshold", color: c.ink3, position: "insideEndTop" },
                data: [{ yAxis: threshold }],
              }
            : undefined,
      })),
    };
  };
}

function DriftDetail({ snap }: { snap: DriftSnapshot }) {
  const metrics = useMemo(() => [...new Set(snap.rows.map((r) => r.metric))], [snap.rows]);
  const [metric, setMetric] = useState("residual_shift");
  const active = metrics.includes(metric) ? metric : metrics[0] ?? "residual_shift";
  const history = useDriftHistory(snap.farm_id, active);
  const build = useCallback((c: ChartColors) => (history.data ? historyOption(history.data)(c) : {}), [history.data]);
  const rows = snap.rows.filter((r) => r.metric === active);

  return (
    <Card
      title={`Farm ${snap.farm_id}: ${DRIFT_METRICS[active] ?? active}`}
      tools={
        <select className="select" value={active} onChange={(e) => setMetric(e.target.value)} aria-label="Drift metric">
          {metrics.map((m) => (
            <option key={m} value={m}>
              {DRIFT_METRICS[m] ?? m}
            </option>
          ))}
        </select>
      }
    >
      <div className="stack">
        <QueryView query={history} height={240}>
          {(h) =>
            Object.keys(h.series).length ? (
              <>
                <Chart build={build} height={260} label={`History of ${active} for farm ${snap.farm_id}`} />
                {Object.keys(h.series).length > 8 && <p className="subtle">Showing the first 8 features; the table lists all.</p>}
              </>
            ) : (
              <Empty title="No history for this metric" />
            )
          }
        </QueryView>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Feature</th>
                <th className="num">Value</th>
                <th className="num">Threshold</th>
                <th>Breached</th>
                <th>Effect</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.metric}-${r.feature}`}>
                  <td>
                    {r.feature_description ?? r.feature ?? "turbine score"}
                    {r.feature && <div className="subtle">{r.feature}</div>}
                  </td>
                  <td className="num">{num(r.value, 4)}</td>
                  <td className="num">{num(r.threshold, 4)}</td>
                  <td>{r.breached ? <Badge tone="critical">breached</Badge> : <Badge tone="good">within</Badge>}</td>
                  <td className="subtle">{r.triggers_retrain ? "triggers retrain" : "informational"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}

function Policy() {
  const policy = useDriftPolicy();
  const schedule = useRetrainSchedule();
  return (
    <Card title="Monitoring & retraining policy">
      <div className="stack" style={{ gap: 12 }}>
        <QueryView query={policy} height={100}>
          {(p) => (
            <dl className="kv">
              <dt>Drift check</dt>
              <dd>every {p.interval_minutes} min over the last {p.window_days} data-days (≥ {p.min_rows.toLocaleString()} rows)</dd>
              {Object.entries(p.metrics).map(([m, cfg]) => (
                <div key={m} style={{ display: "contents" }}>
                  <dt>{DRIFT_METRICS[m] ?? m}</dt>
                  <dd>
                    threshold {String(cfg.threshold)} · {cfg.triggers_retrain ? "triggers retrain" : "informational"}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </QueryView>
        <QueryView query={schedule} height={100}>
          {(s) => (
            <dl className="kv">
              <dt>Scheduled retrain</dt>
              <dd>
                <code>{s.cron}</code> ({s.timezone}) · next {wallTime(s.next_run)}
              </dd>
              <dt>Drift cool-down</dt>
              <dd>{s.drift_cooldown_hours} h between drift-triggered retrains of a farm</dd>
              <dt>Promotion gate</dt>
              <dd>
                CARE-style score must improve by ≥ {s.promotion_gate.min_care_score_improvement}; {s.promotion_gate.false_alarms}
              </dd>
              <dt>Auto-promote</dt>
              <dd>{s.auto_promote ? "yes: a challenger that passes the gate becomes champion" : "no: an admin approves challengers"}</dd>
            </dl>
          )}
        </QueryView>
      </div>
    </Card>
  );
}

function outcome(job: RetrainJob) {
  if (job.status === "failed") return <span className="subtle" title={job.result?.error}>{job.result?.error?.slice(0, 80) ?? "failed"}</span>;
  const reg = job.result?.registry;
  if (!reg) return <span className="subtle">—</span>;
  return reg.promoted ? (
    <Badge tone="good">v{reg.version} promoted</Badge>
  ) : (
    <span>
      <Badge tone="neutral">v{reg.version} held</Badge>
      <div className="subtle" style={{ maxWidth: 360 }}>{reg.gate_reasons.join("; ")}</div>
    </span>
  );
}

function RetrainDialog({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const request = useRequestRetrain();
  const [farm, setFarm] = useState("A");
  const [reason, setReason] = useState("");
  return (
    <Dialog title="Request a retrain" onClose={onClose}>
      <div className="stack" style={{ gap: 12 }}>
        <p className="muted" style={{ margin: 0 }}>
          Runs the full training and evaluation protocol on the curated data of the farm. The new version goes through the same promotion
          gate as scheduled and drift-triggered retrains.
        </p>
        <div className="field">
          <label htmlFor="rt-farm">Farm</label>
          <select id="rt-farm" className="select" value={farm} onChange={(e) => setFarm(e.target.value)}>
            <option value="A">Farm A</option>
            <option value="B">Farm B</option>
            <option value="C">Farm C</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="rt-reason">Reason (recorded in the audit log)</label>
          <textarea id="rt-reason" className="textarea" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
        </div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn primary"
            disabled={reason.trim().length < 3 || request.isPending}
            onClick={() =>
              request.mutate(
                { farm, reason: reason.trim() },
                {
                  onSuccess: (job) => {
                    toast(`Retrain job #${job.id} queued for farm ${farm}`);
                    onClose();
                  },
                  onError: (e) => toast(e.message, "error"),
                },
              )
            }
          >
            Queue retrain
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function Jobs() {
  const jobs = useRetrainJobs();
  return (
    <Card title="Retrain jobs" hint="scheduled, drift-triggered and manual" flush>
      <QueryView query={jobs} height={200}>
        {(list) =>
          list.length ? (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Farm</th>
                    <th>Trigger</th>
                    <th>Status</th>
                    <th>Requested</th>
                    <th className="num">Duration</th>
                    <th className="num">CARE score</th>
                    <th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((j) => (
                    <tr key={j.id}>
                      <td>#{j.id}</td>
                      <td>{j.scope?.farm ?? "—"}</td>
                      <td>
                        {titleCase(j.trigger)}
                        <div className="subtle" style={{ maxWidth: 280 }}>{j.scope?.reason}</div>
                      </td>
                      <td>
                        <Badge tone={{ queued: "neutral", running: "accent", succeeded: "good", failed: "critical" }[j.status]}>{j.status}</Badge>
                      </td>
                      <td>
                        {wallTime(j.requested_at)}
                        <div className="subtle">{j.requested_by}</div>
                      </td>
                      <td className="num">
                        {j.started_at && j.finished_at
                          ? duration((new Date(j.finished_at).getTime() - new Date(j.started_at).getTime()) / 1000)
                          : j.started_at
                            ? "running"
                            : "—"}
                      </td>
                      <td className="num">{num(j.result?.metrics?.care_style_score, 4)}</td>
                      <td>{outcome(j)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="No retrain jobs yet" />
          )
        }
      </QueryView>
    </Card>
  );
}

export function DriftPage() {
  const { can } = useAuth();
  const drift = useDrift();
  const [farm, setFarm] = useState<string | null>(null);
  const [dialog, setDialog] = useState(false);
  const active = drift.data?.find((d) => d.farm_id === farm) ?? drift.data?.[0];

  return (
    <>
      <PageHead
        title="Drift & retraining"
        lede={
          <>
            Live inputs and model scores are compared with each champion's training reference. A retrain-triggering breach queues a
            challenger; scheduled retrains run regardless. Results land in <Link to="/models">Models</Link>.
          </>
        }
        actions={
          can("admin") && (
            <button className="btn primary" onClick={() => setDialog(true)}>
              <RefreshCcw size={14} /> Request retrain
            </button>
          )
        }
      />
      <QueryView query={drift} height={100}>
        {(list) => (
          <div className="grid cols-3" style={{ marginBottom: 16 }}>
            {list.map((d) => (
              <FarmDrift key={d.farm_id} snap={d} selected={d.farm_id === active?.farm_id} onSelect={() => setFarm(d.farm_id)} />
            ))}
          </div>
        )}
      </QueryView>
      <div className="grid cols-main-side" style={{ marginBottom: 16 }}>
        {active ? (
          active.status === "no_data" ? (
            <Card>
              <Empty title={`Farm ${active.farm_id} has not been checked yet`} />
            </Card>
          ) : (
            <DriftDetail key={active.farm_id} snap={active} />
          )
        ) : (
          <div />
        )}
        <Policy />
      </div>
      <Jobs />
      {dialog && <RetrainDialog onClose={() => setDialog(false)} />}
    </>
  );
}

