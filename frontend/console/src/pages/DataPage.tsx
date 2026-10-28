import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useCoverage, useEvents, useQuality, useReplay } from "../api/hooks";
import type { Coverage, QualityRow } from "../api/types";
import { Badge, Card, Empty, PageHead, QueryView, Segmented, Tabs } from "../components/ui";
import { ago, dataDate, dataTime, int, num, pct, titleCase } from "../lib/format";

type Tab = "coverage" | "quality" | "events" | "replay";

function CoverageMatrix({ coverage }: { coverage: Coverage }) {
  const byComponent = useMemo(() => {
    const out: Record<string, Coverage["subparts"]> = {};
    for (const sp of coverage.subparts) (out[sp.component] ??= []).push(sp);
    return Object.entries(out);
  }, [coverage.subparts]);
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Component</th>
            <th>Sub-part</th>
            {coverage.farms.map((f) => (
              <th key={f} className="num">
                Farm {f}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {byComponent.flatMap(([component, subparts]) =>
            subparts.map((sp, i) => (
              <tr key={sp.code}>
                <td style={{ fontWeight: 600 }}>{i === 0 ? titleCase(component) : ""}</td>
                <td>
                  {sp.name}
                  <div className="subtle">{sp.code}</div>
                </td>
                {coverage.farms.map((f) => {
                  const n = coverage.matrix[f]?.[component]?.[sp.code] ?? 0;
                  return (
                    <td key={f} className="num">
                      {n > 0 ? <Badge tone="good">{n} sensor{n === 1 ? "" : "s"}</Badge> : <span className="subtle">not measured</span>}
                    </td>
                  );
                })}
              </tr>
            )),
          )}
        </tbody>
      </table>
    </div>
  );
}

function PctCell({ v, warn }: { v: number; warn: number }) {
  return (
    <td className="num" style={{ color: v >= warn ? "var(--danger-ink)" : undefined }}>
      {num(v, 2)}%
    </td>
  );
}

function QualityTable({ farm }: { farm: string }) {
  const q = useQuality(farm);
  const [sort, setSort] = useState<keyof QualityRow>("stuck_pct");
  return (
    <QueryView query={q} height={300}>
      {(d) => {
        const rows = [...d.sensors].sort((a, b) => Number(b[sort] ?? 0) - Number(a[sort] ?? 0));
        return (
          <>
            <div className="filters" style={{ padding: "12px 16px 0" }}>
              <span className="subtle">
                Data version <code>{d.data_version}</code> · {rows.length} signals
              </span>
              <Segmented
                label="Sort by"
                value={sort}
                onChange={setSort}
                options={[
                  { value: "stuck_pct", label: "Stuck" },
                  { value: "missing_pct", label: "Missing" },
                  { value: "out_of_range_pct", label: "Out of range" },
                ]}
              />
            </div>
            <div className="table-wrap" style={{ maxHeight: 640 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Signal</th>
                    <th>Unit</th>
                    <th className="num">Rows</th>
                    <th className="num">Missing</th>
                    <th className="num">Stuck</th>
                    <th className="num">Out of range</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.sensor}>
                      <td>
                        {r.description ?? r.sensor}
                        <div className="subtle">{r.sensor}</div>
                      </td>
                      <td>{r.unit ?? "—"}</td>
                      <td className="num">{int(r.rows)}</td>
                      <PctCell v={r.missing_pct} warn={5} />
                      <PctCell v={r.stuck_pct} warn={20} />
                      <PctCell v={r.out_of_range_pct} warn={1} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="subtle" style={{ padding: "0 16px 12px" }}>
              Stuck = consecutive identical readings; highlighted cells exceed the review threshold (missing ≥ 5%, stuck ≥ 20%, out of range ≥ 1%).
            </p>
          </>
        );
      }}
    </QueryView>
  );
}

function EventsTable({ farm }: { farm: string }) {
  const q = useEvents(farm);
  return (
    <QueryView query={q} height={300}>
      {(list) =>
        list.length ? (
          <div className="table-wrap" style={{ maxHeight: 680 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Turbine</th>
                  <th>Outcome</th>
                  <th>Component</th>
                  <th>Prediction window</th>
                  <th className="num">Rows</th>
                </tr>
              </thead>
              <tbody>
                {list.map((e) => (
                  <tr key={e.id}>
                    <td>#{e.source_event_id}</td>
                    <td>
                      <Link to={`/turbines/${e.turbine_id}?tab=events`}>{e.turbine_id}</Link>
                    </td>
                    <td>
                      {e.label === "anomaly" ? <Badge tone="critical">Anomaly</Badge> : <Badge tone="good">Normal</Badge>}
                      {e.description && <div className="subtle">{e.description}</div>}
                    </td>
                    <td>{e.component_code ? titleCase(e.component_code) : "—"}</td>
                    <td>
                      {dataDate(e.prediction_start)} → {dataDate(e.event_end)}
                    </td>
                    <td className="num">{int(e.n_rows)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No events" />
        )
      }
    </QueryView>
  );
}

function ReplayTable() {
  const q = useReplay();
  return (
    <QueryView query={q} height={300}>
      {(r) => (
        <>
          <div className="filters" style={{ padding: "12px 16px 0" }}>
            <Badge tone="accent">{r.mode}</Badge>
            <span className="subtle">
              {r.speed.toLocaleString()}× speed · tick {r.tick_seconds} s · last update {ago(r.last_update)}
            </span>
          </div>
          <div className="table-wrap" style={{ maxHeight: 680 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Turbine</th>
                  <th>Data time</th>
                  <th>Source event</th>
                  <th>Operating state</th>
                  <th style={{ width: 200 }}>Progress</th>
                  <th className="num">Rows</th>
                </tr>
              </thead>
              <tbody>
                {r.turbines.map((t) => (
                  <tr key={t.turbine_id}>
                    <td>
                      <Link to={`/turbines/${t.turbine_id}`}>{t.turbine_id}</Link>
                    </td>
                    <td>{dataTime(t.cursor_ts)}</td>
                    <td>{t.source_event_id !== null ? `#${t.source_event_id}` : "—"}</td>
                    <td>{t.operating_status_label ?? "—"}</td>
                    <td>
                      <div className="progress" title={pct(t.progress)}>
                        <div style={{ width: `${t.progress * 100}%` }} />
                      </div>
                      <div className="subtle">
                        {pct(t.progress, 0)} · cycle {t.cycle + 1}
                      </div>
                    </td>
                    <td className="num">
                      {int(t.position)} / {int(t.total_rows)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </QueryView>
  );
}

export function DataPage() {
  const [tab, setTab] = useState<Tab>("coverage");
  const [farm, setFarm] = useState("A");
  const coverage = useCoverage();
  const farmPicker = <Segmented label="Farm" value={farm} onChange={setFarm} options={["A", "B", "C"].map((f) => ({ value: f, label: `Farm ${f}` }))} />;
  return (
    <>
      <PageHead
        title="Data & replay"
        lede="What each farm measures, how clean it is, the labelled CARE events used for evaluation, and the live replay that feeds scoring."
      />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "coverage", label: "Sensor coverage" },
          { id: "quality", label: "Data quality" },
          { id: "events", label: "Labelled events" },
          { id: "replay", label: "Replay status" },
        ]}
      />
      {tab === "coverage" && (
        <Card title="Monitored sensors per sub-part" hint="from the component taxonomy applied to each farm's signal list" flush>
          <QueryView query={coverage} height={400}>
            {(c) => <CoverageMatrix coverage={c} />}
          </QueryView>
        </Card>
      )}
      {tab === "quality" && (
        <Card title="Ingest data-quality report" tools={farmPicker} flush>
          <QualityTable farm={farm} />
        </Card>
      )}
      {tab === "events" && (
        <Card title="CARE events" hint="file name maps each event to exactly one turbine" tools={farmPicker} flush>
          <EventsTable farm={farm} />
        </Card>
      )}
      {tab === "replay" && (
        <Card title="Per-turbine replay" flush>
          <ReplayTable />
        </Card>
      )}
    </>
  );
}
