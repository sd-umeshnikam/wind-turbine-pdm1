// ECharts wrapper. Options are built from resolved theme colours (light/dark), so every
// chart re-renders when the theme changes. Marks follow the data-viz spec: 2px lines,
// recessive grid, one y-axis per chart, crosshair tooltip.

import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";
import { cssVar, useIsDark } from "../lib/theme";

echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
  CanvasRenderer,
]);

export type Option = echarts.EChartsCoreOption;

export interface ChartColors {
  ink1: string;
  ink2: string;
  ink3: string;
  grid: string;
  axis: string;
  surface: string;
  series: string[];
  good: string;
  warning: string;
  serious: string;
  critical: string;
}

export function chartColors(): ChartColors {
  return {
    ink1: cssVar("--ink-1"),
    ink2: cssVar("--ink-2"),
    ink3: cssVar("--ink-3"),
    grid: cssVar("--grid"),
    axis: cssVar("--axis"),
    surface: cssVar("--surface-1"),
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--series-${i}`)),
    good: cssVar("--status-good"),
    warning: cssVar("--status-warning"),
    serious: cssVar("--status-serious"),
    critical: cssVar("--status-critical"),
  };
}

/** Shared frame for time-series charts. */
export function timeFrame(c: ChartColors, opts: { yName?: string; yMin?: number; yMax?: number; legend?: boolean } = {}): Option {
  return {
    animation: false,
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: c.ink2 },
    grid: { left: 56, right: 20, top: opts.legend ? 36 : 16, bottom: 56 },
    legend: opts.legend
      ? { top: 0, left: 0, textStyle: { color: c.ink2 }, icon: "roundRect", itemWidth: 12, itemHeight: 4 }
      : undefined,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: c.axis } },
      backgroundColor: c.surface,
      borderColor: c.grid,
      textStyle: { color: c.ink1, fontSize: 12 },
      valueFormatter: (v: unknown) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"),
    },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: c.axis } },
      axisLabel: { color: c.ink3, hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: opts.yName,
      nameTextStyle: { color: c.ink3, align: "left" },
      min: opts.yMin,
      max: opts.yMax,
      scale: opts.yMin === undefined,
      axisLabel: { color: c.ink3 },
      splitLine: { lineStyle: { color: c.grid } },
    },
    dataZoom: [
      { type: "inside", throttle: 50 },
      { type: "slider", height: 18, bottom: 8, borderColor: c.grid, textStyle: { color: c.ink3 } },
    ],
  };
}

export function Chart({
  build,
  height = 280,
  label,
}: {
  build: (c: ChartColors) => Option;
  height?: number;
  /** Accessible description of what the chart shows. */
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const dark = useIsDark();
  const option = useMemo(() => build(chartColors()), [build, dark]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!ref.current) return;
    const instance = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.current = instance;
    const ro = new ResizeObserver(() => instance.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={ref} className="chart" style={{ height }} role="img" aria-label={label} />;
}
