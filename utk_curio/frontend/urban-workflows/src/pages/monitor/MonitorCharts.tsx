import React, { useEffect, useMemo, useRef } from "react";
import type { DurationBucket, SizeBucket } from "../../api/monitorApi";
import { formatBytes } from "../../utils/diagnosticsBundle";
import { reachVegaTooltips, vegaTooltipHandler } from "../../components/tooltip/vegaTooltip";
import { CATEGORICAL } from "./chartColors";

const vega = require("vega");
const lite = require("vega-lite");

/**
 * The monitor page's charts: two histograms, and lines over time.
 *
 * The histograms are single-series distributions over fixed, ordered bins, so
 * they are drawn identically on purpose: the page should read as one system
 * rather than two charts that happen to sit near each other. `LinesOverTime`
 * draws any hourly history, one line per series, in the same ink.
 *
 * COLOUR. One hue, declared here as a module constant because vega-lite needs a
 * literal and no stylesheet references it. There is no legend: the title names
 * the series, and a legend for one series is furniture. Axis and label ink is
 * deliberately recessive so the bars carry the signal.
 *
 * NO DARK MODE. curioTokens.css declares a single `:root` and the app has no
 * theme toggle, so dark variants here would be unreachable code. This is a
 * decision, not an omission; revisit it when the app gains a theme.
 *
 * WHY NOT useVega. `src/hook/useVega.ts` is bound to the node runtime
 * (useProvenanceContext, useFlowContext, useToastContext, NodeEmptyState) and
 * cannot run off-canvas. This compiles the spec the same way
 * `adapters/vegaLiteAdapter.ts` does, which is the shared path underneath it.
 */
const SERIES = "#2a78d6";
const AXIS_INK = "#6B6B76";
const GRID_INK = "#E5E5E7";

function baseSpec(values: any[], xTitle: string, yTitle: string, xField: string) {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    data: { values },
    // A discrete axis: the bins are ordered categories, not a continuous
    // scale, so they must not be spaced by their numeric bounds.
    mark: { type: "bar", cornerRadiusEnd: 4, color: SERIES },
    encoding: {
      x: {
        field: xField,
        type: "ordinal",
        title: xTitle,
        sort: null,
        axis: { labelAngle: 0, labelColor: AXIS_INK, titleColor: AXIS_INK,
                domainColor: GRID_INK, tickColor: GRID_INK },
      },
      y: {
        field: "count",
        type: "quantitative",
        title: yTitle,
        axis: { labelColor: AXIS_INK, titleColor: AXIS_INK,
                gridColor: GRID_INK, domain: false, tickCount: 4 },
      },
      // A chart that does not respond to hover is a picture of a chart.
      tooltip: [
        { field: xField, type: "ordinal", title: xTitle },
        { field: "count", type: "quantitative", title: "count" },
      ],
    },
    config: {
      background: null,
      view: { stroke: null },
      font: "Rubik, sans-serif",
      bar: { discreteBandSize: { band: 0.85 } },
    },
  };
}

const VegaChart: React.FC<{ spec: any; height: number; label: string }> = ({
  spec,
  height,
  label,
}) => {
  const host = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let view: any;
    try {
      const compiled = lite.compile({ ...spec, width: "container", height }).spec;
      view = new vega.View(vega.parse(compiled), {
        renderer: "svg",
        container: element,
        hover: true,
        // A bar's tooltip in the Curio tooltip, not the browser's title.
        tooltip: vegaTooltipHandler,
      });
      // And the nearest bar's, as the node's charts reach it.
      reachVegaTooltips(view);
      void view.runAsync();
    } catch {
      // A chart that cannot render must not take the page down with it; the
      // numbers it summarises are all on screen as tiles anyway.
      return undefined;
    }
    return () => {
      try {
        view?.finalize();
      } catch {
        /* nothing useful to do on teardown */
      }
    };
  }, [spec, height]);

  // Vega makes the element it draws into a "graphics-document" named "Vega
  // visualization" (vega-view's initializeAria), so the chart's role and name
  // sit on a wrapper Vega never touches.
  return (
    <div aria-label={label} role="img" style={{ width: "100%" }}>
      <div ref={host} style={{ width: "100%" }} />
    </div>
  );
};

function durationBinLabel(bucket: DurationBucket, previous: number | null): string {
  if (bucket.leMs === null) return "> 30s";
  const upper = bucket.leMs >= 1000 ? `${bucket.leMs / 1000}s` : `${bucket.leMs}ms`;
  if (previous === null) return `≤ ${upper}`;
  const lower = previous >= 1000 ? `${previous / 1000}s` : `${previous}ms`;
  return `${lower} to ${upper}`;
}

export const DurationHistogram: React.FC<{ buckets: DurationBucket[] }> = ({
  buckets,
}) => {
  const values = buckets.map((bucket, i) => ({
    bin: durationBinLabel(bucket, i === 0 ? null : buckets[i - 1].leMs),
    count: bucket.count,
  }));
  return (
    <VegaChart
      spec={baseSpec(values, "execution time", "runs", "bin")}
      height={150}
      label="Distribution of node execution times"
    />
  );
};

export const StoreSizeHistogram: React.FC<{ buckets: SizeBucket[] }> = ({
  buckets,
}) => {
  const values = buckets.map((bucket, i) => ({
    bin:
      bucket.leBytes === null
        ? `> ${formatBytes(buckets[i - 1]?.leBytes ?? 0)}`
        : `≤ ${formatBytes(bucket.leBytes)}`,
    count: bucket.count,
  }));
  return (
    <VegaChart
      spec={baseSpec(values, "store size", "stores", "bin")}
      height={150}
      label="Distribution of user store sizes"
    />
  );
};

/** What `LinesOverTime` draws, and how. */
export interface LinesOverTimeOptions {
  /** One point per row: its time (epoch milliseconds), its value and its series. */
  rows: Record<string, unknown>[];
  timeField: string;
  valueField: string;
  /** The field whose values name the lines: one line per value. */
  seriesField: string;
  /** What the y axis and the tooltip call the value. */
  valueTitle: string;
  /** What the tooltip calls the series. */
  seriesTitle?: string;
  /** How the tooltip writes a point's time, in d3-time-format. */
  timeFormat?: string;
  /** The x axis from its first time to its last; the rows' own span when left out. */
  timeDomain?: [number, number];
  /**
   * The series in the legend's order with their colours; when left out, the
   * series in the rows' order with the palette's colours. A chart of more
   * series than the palette's eight passes its own, the rest folded into one.
   */
  colors?: { domain: string[]; range: string[] };
  /** A log y axis, which leaves out a value of 0 or less. */
  logY?: boolean;
  /** The series drawn dashed, as a limit is. */
  dashed?: string[];
  /** A dot on each point, for a chart of few: a line of one point draws nothing else. */
  points?: boolean;
}

/**
 * The Vega-Lite spec of `LinesOverTime`: time on x, the value on y, a 2px
 * line per series, the legend under the plot, and a tooltip with the series,
 * the time and the value.
 */
export function linesOverTimeSpec({
  rows,
  timeField,
  valueField,
  seriesField,
  valueTitle,
  seriesTitle = "series",
  timeFormat = "%b %-d, %H:%M",
  timeDomain,
  colors,
  logY = false,
  dashed = [],
  points = false,
}: LinesOverTimeOptions) {
  const series = colors?.domain ?? [...new Set(rows.map((row) => String(row[seriesField])))];
  const range = colors?.range ?? CATEGORICAL.slice(0, series.length);
  const ink = { labelColor: AXIS_INK, titleColor: AXIS_INK, domainColor: GRID_INK,
                tickColor: GRID_INK, gridColor: GRID_INK };
  const encoding: Record<string, unknown> = {
    x: {
      field: timeField,
      type: "temporal",
      title: null,
      axis: { ...ink, labelFlush: true },
      ...(timeDomain ? { scale: { domain: timeDomain } } : {}),
    },
    y: {
      field: valueField,
      type: "quantitative",
      title: valueTitle,
      axis: { ...ink, domain: false, tickCount: 4, format: "~s" },
      ...(logY ? { scale: { type: "log" } } : {}),
    },
    color: {
      field: seriesField,
      type: "nominal",
      title: null,
      scale: { domain: series, range },
      legend: { orient: "bottom", direction: "horizontal", columns: 2, labelLimit: 320,
                labelColor: AXIS_INK, symbolType: "stroke", symbolStrokeWidth: 2 },
    },
    tooltip: [
      { field: seriesField, type: "nominal", title: seriesTitle },
      { field: timeField, type: "temporal", title: "time", format: timeFormat },
      { field: valueField, type: "quantitative", title: valueTitle, format: "," },
    ],
  };
  if (dashed.length > 0) {
    encoding.strokeDash = {
      field: seriesField,
      type: "nominal",
      legend: null,
      scale: { domain: series, range: series.map((name) => (dashed.includes(name) ? [6, 4] : [1, 0])) },
    };
  }
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    data: { values: rows },
    mark: {
      type: "line",
      strokeWidth: 2,
      strokeCap: "round",
      strokeJoin: "round",
      ...(points ? { point: { filled: true, size: 64 } } : {}),
    },
    encoding,
    config: { background: null, view: { stroke: null }, font: "Rubik, sans-serif" },
  };
}

/**
 * Lines over time, one per series: an hourly history of the monitor's. Its
 * tooltip is the Curio one, as the histograms' is. Pass `rows`, `colors` and
 * `dashed` that keep their identity while they hold the same, or the chart is
 * drawn again at each render.
 */
export const LinesOverTime: React.FC<LinesOverTimeOptions & { label: string; height?: number }> = ({
  label,
  height = 160,
  rows,
  timeField,
  valueField,
  seriesField,
  valueTitle,
  seriesTitle,
  timeFormat,
  timeDomain,
  colors,
  logY,
  dashed,
  points,
}) => {
  const first = timeDomain?.[0];
  const last = timeDomain?.[1];
  const spec = useMemo(
    () =>
      linesOverTimeSpec({
        rows, timeField, valueField, seriesField, valueTitle, seriesTitle, timeFormat,
        timeDomain: first != null && last != null ? [first, last] : undefined,
        colors, logY, dashed, points,
      }),
    [rows, timeField, valueField, seriesField, valueTitle, seriesTitle, timeFormat, first, last, colors, logY,
     dashed, points]
  );
  return <VegaChart spec={spec} height={height} label={label} />;
};
