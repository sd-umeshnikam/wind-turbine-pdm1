import { ExternalLink } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApprove, useComparison, useDeployments, useModelCard, useModels, useVersionCompare } from "../api/hooks";
import type { Comparison, ModelVersion, Row } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Chart, type ChartColors } from "../components/Chart";
import { Markdown } from "../components/Markdown";
import { useToast } from "../components/Toasts";
import { Badge, Banner, Card, Empty, PageHead, QueryView, Segmented, Tabs } from "../components/ui";
import { metricLabel, num, titleCase, wallTime } from "../lib/format";

const HEADLINE = ["care_style_score", "event_recall", "normal_accuracy", "earliness", "false_alarm_days_per_turbine_year"];
const DETECTOR_CHART_METRICS = ["care_style_score", "event_recall", "event_precision", "normal_accuracy", "earliness"];

function AliasBadges({ v }: { v: ModelVersion }) {
  return (
    <span className="row" style={{ gap: 4 }}>
      {v.aliases.includes("champion") && <Badge tone="good">champion</Badge>}
      {v.aliases.includes("challenger") && <Badge tone="accent">challenger</Badge>}
      {!v.aliases.length && <Badge tone="outline">archived</Badge>}
    </span>
  );
}

function fmt(metric: string, v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  if (["detected", "anomaly_events", "normal_events", "false_alarm_events", "pre_onset_alarm_events"].includes(metric)) return num(v, 0);
  if (metric.includes("hours") || metric.includes("days")) return num(v, 1);
  return num(v, 3);
}

function VersionsTable({
  versions,
  selected,
  onSelect,
}: {
  versions: ModelVersion[];
  selected: string | null;
  onSelect: (v: string) => void;
}) {
  const { can } = useAuth();
  const toast = useToast();
  const approve = useApprove(versions[0]?.farm ?? "A");
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Version</th>
            <th>Status</th>
            <th>Trigger</th>
            <th>Detector</th>
            {HEADLINE.map((m) => (
              <th key={m} className="num">
                {metricLabel(m)}
              </th>
            ))}
            <th>Promotion gate</th>
            <th>Registered</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.version} className={`clickable ${v.version === selected ? "selected" : ""}`} onClick={() => onSelect(v.version)}>
              <td style={{ fontWeight: 600 }}>v{v.version}</td>
              <td>
                <AliasBadges v={v} />
              </td>
              <td>
                {v.trigger ?? "—"}
                <div className="subtle">{v.actor}</div>
              </td>
              <td>{v.selected_detector ?? "—"}</td>
              {HEADLINE.map((m) => (
                <td key={m} className="num">
                  {fmt(m, v.metrics[m])}
                </td>
              ))}
              <td style={{ maxWidth: 260 }}>
                {v.gate === "passed" ? <Badge tone="good">passed</Badge> : v.gate ? <><Badge tone="neutral">held</Badge><div className="subtle" style={{ minWidth: 240 }}>{v.gate}</div></> : "—"}
              </td>
              <td>{wallTime(v.created_at)}</td>
              <td onClick={(e) => e.stopPropagation()}>
                <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                  <a className="btn sm ghost" href={v.run_url} target="_blank" rel="noreferrer" title="Open the training run in MLflow">
                    MLflow <ExternalLink size={12} />
                  </a>
                  {can("admin") && v.aliases.includes("challenger") && v.gate === "passed" && (
                    <button
                      className="btn sm primary"
                      disabled={approve.isPending}
                      onClick={() =>
                        approve.mutate(v.version, {
                          onSuccess: () => toast(`v${v.version} promoted to champion`),
                          onError: (e) => toast(`Approval failed: ${e.message}`, "error"),
                        })
                      }
                    >
                      Approve
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CompareCard({ farm, versions }: { farm: string; versions: ModelVersion[] }) {
  const champion = versions.find((v) => v.aliases.includes("champion"))?.version ?? null;
  const challenger = versions.find((v) => v.aliases.includes("challenger"))?.version ?? null;
  const [a, setA] = useState<string | null>(champion);
  const [b, setB] = useState<string | null>(challenger ?? versions.find((v) => v.version !== champion)?.version ?? null);
  useEffect(() => {
    setA(champion);
    setB(challenger ?? versions.find((v) => v.version !== champion)?.version ?? null);
  }, [farm, champion, challenger, versions]);
  const cmp = useVersionCompare(farm, a, b);
  const picker = (value: string | null, set: (v: string) => void, label: string) => (
    <select className="select" value={value ?? ""} onChange={(e) => set(e.target.value)} aria-label={label}>
      {versions.map((v) => (
        <option key={v.version} value={v.version}>
          v{v.version}
          {v.aliases.length ? ` (${v.aliases.join(", ")})` : ""}
        </option>
      ))}
    </select>
  );
  return (
    <Card
      title="Version comparison"
      hint="same evaluation protocol: leave-turbine-out, CARE-style event metrics"
      tools={
        <>
          {picker(a, setA, "Version A")} <span className="subtle">vs</span> {picker(b, setB, "Version B")}
        </>
      }
      flush
    >
      {versions.length < 2 ? (
        <Empty title="Only one version is registered" />
      ) : a === b ? (
        <Empty title="Pick two different versions" />
      ) : (
        <QueryView query={cmp} height={240}>
          {(c) => (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th className="num">v{c.a.version}</th>
                    <th className="num">v{c.b.version}</th>
                    <th className="num">Δ (B − A)</th>
                    <th>Better</th>
                  </tr>
                </thead>
                <tbody>
                  {c.metrics.map((m) => (
                    <tr key={m.metric}>
                      <td>{metricLabel(m.metric)}</td>
                      <td className="num">{fmt(m.metric, m.a)}</td>
                      <td className="num">{fmt(m.metric, m.b)}</td>
                      <td className="num">{m.delta === null ? "—" : `${m.delta > 0 ? "+" : ""}${fmt(m.metric, m.delta)}`}</td>
                      <td>{m.better ? <Badge tone={m.better === c.b.version ? "accent" : "neutral"}>v{m.better}</Badge> : <span className="subtle">tie / n.a.</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryView>
      )}
    </Card>
  );
}

function RowsTable({ rows, highlight }: { rows: Row[]; highlight?: (r: Row) => boolean }) {
  if (!rows.length) return <Empty title="Nothing recorded for this run" />;
  const cols = Object.keys(rows[0]!);
  return (
    <div className="table-wrap" style={{ maxHeight: 520 }}>
      <table className="data">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c} className={typeof rows[0]![c] === "number" ? "num" : undefined}>
                {metricLabel(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={highlight?.(r) ? "highlight" : undefined}>
              {cols.map((c) => {
                const v = r[c];
                return (
                  <td key={c} className={typeof v === "number" ? "num" : undefined}>
                    {typeof v === "number" ? fmt(c, v) : typeof v === "boolean" ? (v ? "yes" : "") : v ?? "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DetectorChart({ comparison }: { comparison: Comparison }) {
  const build = useCallback(
    (c: ChartColors) => ({
      animation: false,
      textStyle: { color: c.ink2 },
      grid: { left: 180, right: 24, top: 36, bottom: 24 },
      legend: { top: 0, left: 0, textStyle: { color: c.ink2 }, icon: "roundRect", itemWidth: 12, itemHeight: 8 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: c.surface, borderColor: c.grid, textStyle: { color: c.ink1 } },
      xAxis: { type: "value", min: 0, max: 1, axisLabel: { color: c.ink3 }, splitLine: { lineStyle: { color: c.grid } } },
      yAxis: {
        type: "category",
        inverse: true,
        data: DETECTOR_CHART_METRICS.map(metricLabel),
        axisLabel: { color: c.ink2 },
        axisLine: { lineStyle: { color: c.axis } },
      },
      series: comparison.detectors.map((d, i) => ({
        name: `${String(d.detector)}${d.selected ? " (selected)" : ""}`,
        type: "bar",
        barGap: "10%",
        barMaxWidth: 14,
        color: c.series[i % c.series.length],
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        data: DETECTOR_CHART_METRICS.map((m) => d[m] as number | null),
      })),
    }),
    [comparison],
  );
  return <Chart build={build} height={300} label="Detector comparison on event metrics" />;
}

type DetailTab = "detectors" | "nbm" | "components" | "rul" | "card";

function VersionDetail({ farm, version }: { farm: string; version: string }) {
  const [tab, setTab] = useState<DetailTab>("detectors");
  const comparison = useComparison(farm, version);
  const card = useModelCard(farm, version);
  return (
    <Card title={`Training run of v${version}`} hint="what the run compared before selecting the deployed configuration">
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "detectors", label: "Anomaly detectors" },
          { id: "nbm", label: "Normal-behaviour models" },
          { id: "components", label: "Per component" },
          { id: "rul", label: "RUL (experimental)" },
          { id: "card", label: "Model card" },
        ]}
      />
      {tab === "card" ? (
        <QueryView query={card} height={300}>
          {(md) => <Markdown>{md}</Markdown>}
        </QueryView>
      ) : (
        <QueryView query={comparison} height={300}>
          {(c) => (
            <>
              {tab === "detectors" && (
                <div className="stack">
                  <DetectorChart comparison={c} />
                  <RowsTable rows={c.detectors} highlight={(r) => r.selected === true} />
                  <p className="subtle" style={{ margin: 0 }}>
                    CARE-style score combines coverage and earliness on anomaly events with accuracy on normal events. Bold = selected for
                    deployment. False-alarm days are per turbine-year of normal operation.
                  </p>
                </div>
              )}
              {tab === "nbm" && (
                <div className="stack">
                  <RowsTable rows={c.nbm} />
                  <p className="subtle" style={{ margin: 0 }}>
                    Per monitored sensor: candidate regressors predicting the healthy value from operating conditions, scored on held-out normal
                    data (NRMSE lower is better, R² higher is better). The selected candidate serves expected values.
                  </p>
                </div>
              )}
              {tab === "components" && <RowsTable rows={c.components} />}
              {tab === "rul" && (
                <div className="stack">
                  <Banner tone="warn">
                    Remaining-useful-life estimates are experimental: few labelled failures per farm. They are evaluated with grouped
                    cross-validation and are not used for alerts.
                  </Banner>
                  <RowsTable rows={c.rul} />
                </div>
              )}
            </>
          )}
        </QueryView>
      )}
    </Card>
  );
}

function Deployments({ farm }: { farm: string }) {
  const q = useDeployments(farm);
  return (
    <Card title="Deployment history" hint="registry alias changes mirrored to the platform" flush>
      <QueryView query={q} height={160}>
        {(rows) =>
          rows.length ? (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Version</th>
                    <th>Alias</th>
                    <th>Validation</th>
                    <th className="num">CARE score</th>
                    <th>By</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d) => (
                    <tr key={d.id}>
                      <td>{wallTime(d.promoted_at)}</td>
                      <td>v{d.version}</td>
                      <td>{d.alias}</td>
                      <td>{titleCase(d.validation)}</td>
                      <td className="num">{fmt("care_style_score", d.metrics?.care_style_score)}</td>
                      <td>{d.promoted_by}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="No deployments yet" />
          )
        }
      </QueryView>
    </Card>
  );
}

export function ModelsPage() {
  const [params, setParams] = useSearchParams();
  const farm = params.get("farm") ?? "A";
  const models = useModels();
  const versions = useMemo(() => models.data?.find((m) => m.farm === farm)?.versions ?? [], [models.data, farm]);
  const champion = versions.find((v) => v.aliases.includes("champion"));
  const [selected, setSelected] = useState<string | null>(null);
  const active = selected && versions.some((v) => v.version === selected) ? selected : champion?.version ?? versions[0]?.version ?? null;

  return (
    <>
      <PageHead
        title="Models"
        lede="Health models per farm in the MLflow registry: every version's evaluation, champion vs challenger, and the candidate comparison of each training run."
        actions={
          <Segmented
            label="Farm"
            value={farm}
            onChange={(f) => {
              setSelected(null);
              setParams({ farm: f }, { replace: true });
            }}
            options={[
              { value: "A", label: "Farm A" },
              { value: "B", label: "Farm B" },
              { value: "C", label: "Farm C" },
            ]}
          />
        }
      />
      <QueryView query={models} height={300}>
        {() =>
          versions.length ? (
            <div className="stack">
              <Card title={`wtpdm-health-${farm}`} hint="click a version for its training run" flush>
                <VersionsTable versions={versions} selected={active} onSelect={setSelected} />
              </Card>
              <CompareCard farm={farm} versions={versions} />
              {active && <VersionDetail farm={farm} version={active} />}
              <Deployments farm={farm} />
            </div>
          ) : (
            <Card>
              <Empty title={`No registered model for farm ${farm}`}>Run training to register the first version.</Empty>
            </Card>
          )
        }
      </QueryView>
    </>
  );
}
