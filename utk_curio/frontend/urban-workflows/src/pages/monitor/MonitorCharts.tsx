import React, { useEffect, useRef } from "react";
import type { DurationBucket, SizeBucket } from "../../api/monitorApi";
import { formatBytes } from "../../utils/diagnosticsBundle";

const vega = require("vega");
const lite = require("vega-lite");

/**
 * The two histograms on the monitor page.
 *
 * Both are single-series distributions over fixed, ordered bins, so they are
 * drawn identically on purpose: the page should read as one system rather than
 * two charts that happen to sit near each other.
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
      });
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

  return <div ref={host} aria-label={label} role="img" style={{ width: "100%" }} />;
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
