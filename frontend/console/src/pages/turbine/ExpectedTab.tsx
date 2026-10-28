import { useCallback, useMemo, useState } from "react";
import { useExpected } from "../../api/hooks";
import type { ExpectedResponse, TurbineDetail } from "../../api/types";
import { Chart, timeFrame, type ChartColors } from "../../components/Chart";
import { Badge, Card, Empty, ErrorState, Loading, Segmented } from "../../components/ui";
import { num } from "../../lib/format";
import { windowFrom } from "../../lib/range";

const SPANS = [
  { value: 1, label: "24 h" },
  { value: 7, label: "7 d" },
  { value: 30, label: "30 d" },
];

function valueOption(d: ExpectedResponse) {
  return (c: ChartColors) => ({
    ...timeFrame(c, { legend: true, yName: d.sensor.unit ?? undefined }),
    series: [
      {
        name: "Measured",
        type: "line",
        showSymbol: false,
        color: c.series[0],
        lineStyle: { width: 2 },
        data: d.points.map((p) => [p.ts, p.actual]),
      },
      {
        name: "Expected (healthy)",
        type: "line",
        showSymbol: false,
        color: c.series[1],
        lineStyle: { width: 2, type: "dashed" },
        data: d.points.map((p) => [p.ts, p.expected]),
      },
    ],
  });
}

function residualOption(d: ExpectedResponse) {
  return (c: ChartColors) => ({
    ...timeFrame(c, { yName: "z" }),
    series: [
      {
        name: "Residual z",
        type: "line",
        showSymbol: false,
        color: c.series[6],
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.08 },
        data: d.points.map((p) => [p.ts, p.residual_z]),
        markLine: { silent: true, symbol: "none", lineStyle: { color: c.axis }, label: { show: false }, data: [{ yAxis: 0 }] },
      },
    ],
  });
}

export function ExpectedTab({ turbine, initialSensor }: { turbine: TurbineDetail; initialSensor: string | null }) {
  const options = useMemo(
    () =>
      turbine.components_tree.flatMap((c) =>
        c.subparts.flatMap((sp) => sp.sensors.map((s) => ({ ...s, subpart: sp.name, component: c.name, health: sp.health }))),
      ),
    [turbine.components_tree],
  );
  const fallback = useMemo(() => {
    const scored = [...options].filter((o) => o.health !== null).sort((a, b) => (a.health ?? 0) - (b.health ?? 0));
    return scored[0]?.code ?? options[0]?.code ?? null;
  }, [options]);
  const [sensor, setSensor] = useState<string | null>(initialSensor);
  const active = sensor ?? fallback;
  const [days, setDays] = useState(7);
  const q = useExpected(turbine.id, active, { from: windowFrom(turbine.replay?.cursor_ts, days), points: 500 });
  const buildValue = useCallback((c: ChartColors) => (q.data ? valueOption(q.data)(c) : {}), [q.data]);
  const buildResidual = useCallback((c: ChartColors) => (q.data ? residualOption(q.data)(c) : {}), [q.data]);

  if (!options.length) return <Card><Empty title="No monitored sensors on this turbine" /></Card>;

  const meanAbsZ = q.data?.points.length
    ? q.data.points.reduce((s, p) => s + Math.abs(p.residual_z ?? 0), 0) / q.data.points.length
    : null;

  return (
    <div className="stack">
      <div className="filters" style={{ marginBottom: 0 }}>
        <select className="select" value={active ?? ""} onChange={(e) => setSensor(e.target.value)} aria-label="Sensor" style={{ maxWidth: 520 }}>
          {[...new Set(options.map((o) => o.component))].map((comp) => (
            <optgroup key={comp} label={comp}>
              {options
                .filter((o) => o.component === comp)
                .map((o) => (
                  <option key={o.code} value={o.code}>
                    {o.subpart}: {o.description} ({o.code})
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
        <Segmented label="Window" value={days} onChange={setDays} options={SPANS} />
        {q.data && (
          <>
            <Badge tone="accent">model {q.data.model_version}</Badge>
            <Badge tone="outline">regressor {q.data.nbm_candidate}</Badge>
            {meanAbsZ !== null && <Badge tone="outline">mean |z| {num(meanAbsZ, 2)}</Badge>}
          </>
        )}
      </div>
      {q.isLoading ? (
        <Loading height={360} />
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} />
        </Card>
      ) : q.data && q.data.points.length ? (
        <>
          <Card
            title={`${q.data.sensor.description}: measured vs expected`}
            hint="expected = what the champion's normal-behaviour model predicts for a healthy turbine under the same operating conditions"
          >
            <Chart build={buildValue} height={320} label={`Measured and expected ${q.data.sensor.description}`} />
          </Card>
          <Card title="Standardised residual" hint="(measured − expected) / normal residual spread of this turbine">
            <Chart build={buildResidual} height={200} label={`Residual z of ${q.data.sensor.description}`} />
          </Card>
        </>
      ) : (
        <Card>
          <Empty title="No replayed data in this window" />
        </Card>
      )}
    </div>
  );
}
