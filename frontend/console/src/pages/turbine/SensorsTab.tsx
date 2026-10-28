import { useCallback, useMemo, useState } from "react";
import { useSensors, useTelemetry } from "../../api/hooks";
import type { Sensor, SensorSeries, TurbineDetail } from "../../api/types";
import { Chart, timeFrame, type ChartColors } from "../../components/Chart";
import { Card, Empty, QueryView, Segmented } from "../../components/ui";
import { SPANS, windowFrom, type SpanDays } from "../../lib/range";

const MAX_SENSORS = 6;

function SensorChart({ series }: { series: SensorSeries }) {
  // One chart per sensor (small multiples): signals in different units never share an axis.
  const build = useCallback(
    (c: ChartColors) => ({
      ...timeFrame(c, { yName: series.unit ?? undefined }),
      grid: { left: 56, right: 16, top: 24, bottom: 48 },
      series: [
        {
          name: "min",
          type: "line",
          stack: "band",
          showSymbol: false,
          lineStyle: { opacity: 0 },
          data: series.points.map((p) => [p.ts, p.min]),
          tooltip: { show: false },
        },
        {
          name: "range",
          type: "line",
          stack: "band",
          showSymbol: false,
          lineStyle: { opacity: 0 },
          areaStyle: { color: c.series[0], opacity: 0.12 },
          data: series.points.map((p) => [p.ts, p.max !== null && p.min !== null ? p.max - p.min : null]),
          tooltip: { show: false },
        },
        {
          name: "average",
          type: "line",
          showSymbol: false,
          color: c.series[0],
          lineStyle: { width: 2 },
          data: series.points.map((p) => [p.ts, p.avg]),
        },
      ],
    }),
    [series],
  );
  return (
    <Card title={series.description} hint={`${series.code}${series.unit ? ` · ${series.unit}` : ""} · band = bucket min–max`}>
      {series.points.length ? (
        <Chart build={build} height={220} label={`${series.description} over time`} />
      ) : (
        <Empty title="No readings in this window" />
      )}
    </Card>
  );
}

export function SensorsTab({ turbine }: { turbine: TurbineDetail }) {
  const catalog = useSensors(turbine.farm_id);
  const [days, setDays] = useState<SpanDays>(7);
  const [q, setQ] = useState("");
  const defaults = useMemo(() => {
    const kinds = ["power", "wind_speed"];
    return (catalog.data ?? []).filter((s) => s.condition_kind && kinds.includes(s.condition_kind)).slice(0, 2).map((s) => s.code);
  }, [catalog.data]);
  const [picked, setPicked] = useState<string[] | null>(null);
  const selected = picked ?? defaults;
  const telemetry = useTelemetry(turbine.id, selected, { from: windowFrom(turbine.replay?.cursor_ts, days), points: 400 });

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = (catalog.data ?? []).filter((s) => !needle || `${s.code} ${s.description}`.toLowerCase().includes(needle));
    const by: Record<string, Sensor[]> = {};
    for (const s of list) {
      const key = s.role === "monitored" ? `Monitored · ${s.subcomponent_code ?? "other"}` : s.role === "condition" ? "Operating conditions" : "Other signals";
      (by[key] ??= []).push(s);
    }
    return Object.entries(by).sort(([a], [b]) => a.localeCompare(b));
  }, [catalog.data, q]);

  const toggle = (code: string) =>
    setPicked(selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code].slice(-MAX_SENSORS));

  return (
    <div className="grid cols-main-side">
      <div className="stack">
        <div className="filters" style={{ marginBottom: 0 }}>
          <Segmented label="Window" value={days} onChange={setDays} options={SPANS.map((s) => ({ value: s.value, label: s.label }))} />
          <span className="subtle">10-minute SCADA averages, downsampled; times on the turbine's data clock</span>
        </div>
        {selected.length === 0 ? (
          <Card>
            <Empty title="Select signals on the right" />
          </Card>
        ) : (
          <QueryView query={telemetry} height={300}>
            {(d) => (
              <div className="grid cols-2">
                {d.series.map((s) => (
                  <SensorChart key={s.code} series={s} />
                ))}
              </div>
            )}
          </QueryView>
        )}
      </div>
      <Card title="Signals" hint={`${selected.length} / ${MAX_SENSORS} selected`}>
        <input
          className="input"
          placeholder="Search signals"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search signals"
          style={{ width: "100%", marginBottom: 8 }}
        />
        <QueryView query={catalog} height={300}>
          {() => (
            <div className="checkbox-list" style={{ maxHeight: 560 }}>
              {groups.map(([group, sensors]) => (
                <div key={group}>
                  <div className="subtle" style={{ padding: "8px 6px 2px", fontWeight: 600 }}>
                    {group}
                  </div>
                  {sensors.map((s) => (
                    <label key={s.code}>
                      <input type="checkbox" checked={selected.includes(s.code)} onChange={() => toggle(s.code)} />
                      <span>
                        {s.description}
                        <div className="subtle">
                          {s.code}
                          {s.unit ? ` · ${s.unit}` : ""}
                        </div>
                      </span>
                    </label>
                  ))}
                </div>
              ))}
            </div>
          )}
        </QueryView>
      </Card>
    </div>
  );
}
