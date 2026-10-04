/**
 * What a Compare Scenarios node (#662) keeps at `metadata.compareScenarios`:
 *
 * - `inputs`, one label per input circle, in circle order: the scenario the
 *   input's node belongs to (its id, name and color), or, for a node in no
 *   scenario, the node's name and a neutral color. The node's code is written
 *   from them, and the stacked table carries them.
 * - `chart`, what its Chart tab draws from that table: a preset, the columns it
 *   reads as x and y, and the aggregate that combines the y values.
 *
 * Written only when present, so a dataflow without one serializes as before.
 */
import { SCENARIO_COLOR_RE } from "../scenarios/scenarioModel";

export interface CompareInputLabel {
  /** The scenario's id; absent for a node in no scenario. */
  scenario?: string;
  name: string;
  /** A CSS hex color, `#rrggbb`. */
  color: string;
}

export const COMPARE_PRESETS = ["bar", "grouped-bar", "line", "scatter", "pie", "lollipop", "table"] as const;
export type ComparePreset = (typeof COMPARE_PRESETS)[number];

export const COMPARE_AGGREGATES = ["mean", "sum", "median", "min", "max", "count"] as const;
export type CompareAggregate = (typeof COMPARE_AGGREGATES)[number];

export interface CompareChart {
  preset?: ComparePreset;
  x?: string;
  y?: string;
  aggregate?: CompareAggregate;
}

export interface CompareSettings {
  inputs?: CompareInputLabel[];
  chart?: CompareChart;
}

/** The color of an input whose node is in no scenario. */
export const NO_SCENARIO_COLOR = "#8a8f98";

const nonEmpty = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;

function normalizeLabel(raw: unknown): CompareInputLabel | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const entry = raw as Record<string, unknown>;
  if (!nonEmpty(entry.name) || typeof entry.color !== "string" || !SCENARIO_COLOR_RE.test(entry.color)) return null;
  const label: CompareInputLabel = { name: entry.name, color: entry.color };
  if (nonEmpty(entry.scenario)) label.scenario = entry.scenario;
  return label;
}

function normalizeChart(raw: unknown): CompareChart | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const entry = raw as Record<string, unknown>;
  const chart: CompareChart = {};
  if ((COMPARE_PRESETS as readonly unknown[]).includes(entry.preset)) chart.preset = entry.preset as ComparePreset;
  if (nonEmpty(entry.x)) chart.x = entry.x;
  if (nonEmpty(entry.y)) chart.y = entry.y;
  if ((COMPARE_AGGREGATES as readonly unknown[]).includes(entry.aggregate)) {
    chart.aggregate = entry.aggregate as CompareAggregate;
  }
  return Object.keys(chart).length > 0 ? chart : undefined;
}

/**
 * The well-formed parts of *raw*, or undefined when nothing is left. The
 * inputs are kept whole or not at all: dropping one label would shift every
 * later one onto the wrong circle.
 */
export function normalizeCompareSettings(raw: unknown): CompareSettings | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const entry = raw as Record<string, unknown>;
  const settings: CompareSettings = {};
  if (Array.isArray(entry.inputs) && entry.inputs.length > 0) {
    const labels = entry.inputs.map(normalizeLabel);
    if (labels.every((label): label is CompareInputLabel => label !== null)) settings.inputs = labels;
  }
  const chart = normalizeChart(entry.chart);
  if (chart) settings.chart = chart;
  return Object.keys(settings).length > 0 ? settings : undefined;
}

/** Whether two label lists say the same thing, circle by circle. */
export function sameLabels(a: readonly CompareInputLabel[] | undefined, b: readonly CompareInputLabel[] | undefined): boolean {
  const left = a ?? [];
  const right = b ?? [];
  return (
    left.length === right.length &&
    left.every(
      (label, i) =>
        label.name === right[i].name && label.color === right[i].color && (label.scenario ?? null) === (right[i].scenario ?? null),
    )
  );
}
