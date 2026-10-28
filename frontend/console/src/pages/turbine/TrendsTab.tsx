import { useCallback, useMemo, useState } from "react";
import { useHealthTrend } from "../../api/hooks";
import type { HealthSeriesResponse, TurbineDetail } from "../../api/types";
import { Chart, timeFrame, type ChartColors } from "../../components/Chart";
import { Card, Empty, QueryView, Segmented } from "../../components/ui";
import { SPANS, windowFrom, type SpanDays } from "../../lib/range";

const MAX_SERIES = 6; // turbine + five sub-parts keeps the categorical colours distinguishable

function buildOption(data: HealthSeriesResponse) {
  return (c: ChartColors) => {
    const bucketMs = data.window.bucket_seconds * 1000;
    const series = data.series.map((s, i) => ({
      name: s.name,
      type: "line",
      showSymbol: false,
      lineStyle: { width: s.subcomponent === "turbine" ? 2.5 : 2 },
      color: c.series[i % c.series.length],
      data: s.points.map((p) => [p.ts, p.avg]),
      markArea:
        s.subcomponent === "turbine" && s.alarm_ts.length
          ? {
              silent: true,
              itemStyle: { color: c.critical, opacity: 0.12 },
              data: s.alarm_ts.map((ts) => [{ xAxis: ts }, { xAxis: new Date(new Date(ts).getTime() + bucketMs).toISOString() }]),
            }
          : undefined,
      markLine:
        i === 0
          ? {
              silent: true,
              symbol: "none",
              lineStyle: { color: c.critical, type: "dashed", width: 1 },
              label: { formatter: "alarm level", color: c.ink3, position: "insideEndTop" },
              data: [{ yAxis: 50 }],
            }
          : undefined,
    }));
    return { ...timeFrame(c, { yMin: 0, yMax: 100, legend: true, yName: "health" }), series };
  };
}

export function TrendsTab({ turbine }: { turbine: TurbineDetail }) {
  const subparts = useMemo(() => turbine.components_tree.flatMap((c) => c.subparts), [turbine.components_tree]);
  const worst = useMemo(
    () =>
      [...subparts]
        .filter((s) => s.health !== null)
        .sort((a, b) => (a.health ?? 0) - (b.health ?? 0))
        .slice(0, 3)
        .map((s) => s.code),
    [subparts],
  );
  const [days, setDays] = useState<SpanDays>(7);
  const [picked, setPicked] = useState<string[] | null>(null);
  const selected = picked ?? worst;
  const codes = ["turbine", ...selected];
  const trend = useHealthTrend(turbine.id, codes, { from: windowFrom(turbine.replay?.cursor_ts, days), points: 600 });
  const build = useCallback((c: ChartColors) => (trend.data ? buildOption(trend.data)(c) : {}), [trend.data]);

  const toggle = (code: string) => {
    const next = selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code];
    setPicked(next.slice(0, MAX_SERIES - 1));
  };

  return (
    <div className="grid cols-main-side">
      <Card
        title="Health over time"
        hint="bucket average · shaded = detector in alarm"
        tools={<Segmented label="Window" value={days} onChange={setDays} options={SPANS.map((s) => ({ value: s.value, label: s.label }))} />}
      >
        <QueryView query={trend} height={360}>
          {(d) =>
            d.series.length ? (
              <Chart build={build} height={380} label={`Health of ${turbine.id} and selected sub-parts over time`} />
            ) : (
              <Empty title="No health scores in this window">The replay has not scored this period yet.</Empty>
            )
          }
        </QueryView>
      </Card>
      <Card title="Sub-parts" hint={`up to ${MAX_SERIES - 1}`}>
        <div className="checkbox-list">
          {subparts.map((s) => (
            <label key={s.code}>
              <input
                type="checkbox"
                checked={selected.includes(s.code)}
                onChange={() => toggle(s.code)}
                disabled={!selected.includes(s.code) && selected.length >= MAX_SERIES - 1}
              />
              <span>
                {s.name}
                <div className="subtle">{s.code.split(".")[0]}</div>
              </span>
            </label>
          ))}
        </div>
      </Card>
    </div>
  );
}
