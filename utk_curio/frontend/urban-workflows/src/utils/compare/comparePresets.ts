/**
 * The Vega-Lite specs a Compare Scenarios node (#662) draws its stacked table
 * with. Each preset reads the table's `scenario_name` column and colors by it,
 * in the scenarios' own colors, in the order of the node's inputs. The spec
 * goes through the Vega-Lite node's code path (`useVega`), which puts the rows
 * in as `input_0`, so no spec here has a `data` block.
 *
 * `comparePresets.cases.json` holds one spec per preset: Jest checks that
 * these functions write exactly those, and pytest checks each against the
 * Vega-Lite schema and the columns it reads.
 *
 * Pure, with no `vega` / `vega-lite` import, so it is testable under jest.
 */
import { VEGA_SCHEMA_URL } from "../../generated/visDefaults";
import { classifyColumns, type ClassifiedColumn } from "../starterSpec";
import {
  COMPARE_PRESETS,
  type CompareAggregate,
  type CompareChart,
  type CompareInputLabel,
  type ComparePreset,
} from "./compareSettings";

/** The stacked table's two leading columns (`scenario_stack.py`). */
export const SCENARIO_FIELD = "scenario";
export const SCENARIO_NAME_FIELD = "scenario_name";

export const PRESET_LABELS: Record<ComparePreset, string> = {
  bar: "Bars",
  "grouped-bar": "Grouped bars",
  line: "Lines",
  scatter: "Points",
  pie: "Pie",
  lollipop: "Lollipops",
  table: "Table",
};

export const AGGREGATE_LABELS: Record<CompareAggregate, string> = {
  mean: "Mean",
  sum: "Sum",
  median: "Median",
  min: "Minimum",
  max: "Maximum",
  count: "Count of rows",
};

/**
 * What each preset reads: an `x` column (a category for grouped bars, any
 * column along the axis of a line, a measure for points), a `y` measure, and
 * whether the y values of a group are combined.
 */
export const PRESET_FIELDS: Record<
  ComparePreset,
  { x: "none" | "category" | "axis" | "measure"; y: boolean; aggregate: CompareAggregate | null }
> = {
  bar: { x: "none", y: true, aggregate: "mean" },
  "grouped-bar": { x: "category", y: true, aggregate: "mean" },
  line: { x: "axis", y: true, aggregate: "mean" },
  scatter: { x: "measure", y: true, aggregate: null },
  pie: { x: "none", y: true, aggregate: "sum" },
  lollipop: { x: "none", y: true, aggregate: "mean" },
  table: { x: "none", y: false, aggregate: null },
};

/** How many rows and columns the table preset shows. */
export const TABLE_ROWS = 40;
export const TABLE_COLUMNS = 8;

/** The stacked table's columns a chart can read, with their roles: not the
 * scenario columns, which every preset reads by itself, and not a geometry. */
export function chartColumns(
  schema: Record<string, string> | null | undefined,
  rows: any[] | null | undefined,
  geometryName?: string | null,
): ClassifiedColumn[] {
  return classifyColumns(schema, rows, geometryName).filter(
    (column) => column.role !== "geometry" && column.name !== SCENARIO_FIELD && column.name !== SCENARIO_NAME_FIELD,
  );
}

export interface ResolvedChart {
  preset: ComparePreset;
  x?: string;
  y?: string;
  aggregate: CompareAggregate | null;
}

const named = (columns: readonly ClassifiedColumn[], role: ClassifiedColumn["role"]) =>
  columns.filter((column) => column.role === role).map((column) => column.name);

/**
 * *chart* with what it leaves unset chosen from *columns*: bars of the first
 * measure, or a table when there is none. A column it names that the table no
 * longer has is chosen again.
 */
export function resolveChart(chart: CompareChart | undefined, columns: readonly ClassifiedColumn[]): ResolvedChart {
  const measures = named(columns, "quantitative");
  const categories = named(columns, "nominal");
  const times = named(columns, "temporal");
  const all = columns.map((column) => column.name);
  const preset: ComparePreset =
    chart?.preset && (COMPARE_PRESETS as readonly string[]).includes(chart.preset)
      ? chart.preset
      : measures.length > 0
        ? "bar"
        : "table";
  const fields = PRESET_FIELDS[preset];
  const resolved: ResolvedChart = { preset, aggregate: fields.aggregate ? chart?.aggregate ?? fields.aggregate : null };

  if (fields.y) {
    const y = chart?.y && measures.includes(chart.y) ? chart.y : measures[0];
    if (y !== undefined) resolved.y = y;
  }
  const keep = (choices: string[]) =>
    chart?.x && choices.includes(chart.x) ? chart.x : choices.find((name) => name !== resolved.y);
  if (fields.x === "category") resolved.x = keep(categories);
  else if (fields.x === "axis") resolved.x = keep([...times, ...measures, ...categories].filter((n) => all.includes(n)));
  else if (fields.x === "measure") resolved.x = keep(measures);
  if (resolved.x === undefined) delete resolved.x;
  return resolved;
}

/** A column name as a Vega-Lite field: a dot or a bracket in it is the
 * column's own, not a path into it. */
export function vegaField(name: string): string {
  return name.replace(/\\/g, "\\\\").replace(/\./g, "\\.").replace(/\[/g, "\\[").replace(/\]/g, "\\]");
}

/** The scenarios' names and colors, each name once, in input order. */
export function scenarioScale(labels: readonly CompareInputLabel[]): { domain: string[]; range: string[] } {
  const domain: string[] = [];
  const range: string[] = [];
  for (const label of labels) {
    if (domain.includes(label.name)) continue;
    domain.push(label.name);
    range.push(label.color);
  }
  return { domain, range };
}

function measure(y: string, aggregate: CompareAggregate | null, type = "quantitative"): Record<string, unknown> {
  if (aggregate === "count") return { aggregate: "count", type, title: "Rows" };
  const title = aggregate ? `${aggregate} of ${y}` : y;
  return { field: vegaField(y), type, ...(aggregate ? { aggregate } : {}), title };
}

function columnType(name: string, columns: readonly ClassifiedColumn[]): string {
  return columns.find((column) => column.name === name)?.role ?? "nominal";
}

export type PresetSpec = { spec: Record<string, unknown> } | { problem: string };

/**
 * The Vega-Lite spec for *chart* over the stacked table of *columns*, colored
 * by *labels*, or why it cannot be drawn.
 */
export function compareChartSpec(
  chart: ResolvedChart,
  labels: readonly CompareInputLabel[],
  columns: readonly ClassifiedColumn[],
): PresetSpec {
  const scale = scenarioScale(labels);
  const color = { field: SCENARIO_NAME_FIELD, type: "nominal", title: "Scenario", scale };
  const scenarioAxis = { field: SCENARIO_NAME_FIELD, type: "nominal", title: "Scenario", sort: scale.domain };
  const fields = PRESET_FIELDS[chart.preset];
  const countOnly = chart.aggregate === "count";
  if (fields.y && chart.y === undefined && !countOnly) {
    return { problem: "The stacked table has no number column to chart. Pick Table, or count rows." };
  }
  if (fields.x !== "none" && chart.x === undefined) {
    return { problem: `${PRESET_LABELS[chart.preset]} need a second column the stacked table does not have. Pick another chart.` };
  }
  const y = chart.y ?? "";
  const base = { $schema: VEGA_SCHEMA_URL };

  switch (chart.preset) {
    case "bar":
      return {
        spec: {
          ...base,
          mark: { type: "bar", tooltip: true },
          encoding: { x: { ...scenarioAxis, axis: { labelAngle: 0 } }, y: measure(y, chart.aggregate), color },
        },
      };
    case "grouped-bar":
      return {
        spec: {
          ...base,
          mark: { type: "bar", tooltip: true },
          encoding: {
            x: { field: vegaField(chart.x!), type: "nominal", title: chart.x },
            xOffset: { field: SCENARIO_NAME_FIELD, type: "nominal", sort: scale.domain },
            y: measure(y, chart.aggregate),
            color,
          },
        },
      };
    case "line":
      return {
        spec: {
          ...base,
          mark: { type: "line", point: true, tooltip: true },
          encoding: {
            x: { field: vegaField(chart.x!), type: columnType(chart.x!, columns), title: chart.x },
            y: measure(y, chart.aggregate),
            color,
          },
        },
      };
    case "scatter":
      return {
        spec: {
          ...base,
          mark: { type: "point", filled: true, tooltip: true },
          encoding: {
            x: { field: vegaField(chart.x!), type: "quantitative", title: chart.x },
            y: { field: vegaField(y), type: "quantitative", title: y },
            color,
          },
        },
      };
    case "pie":
      return {
        spec: {
          ...base,
          mark: { type: "arc", tooltip: true },
          encoding: { theta: measure(y, chart.aggregate), color },
        },
      };
    case "lollipop": {
      // A stem from zero to the value, and a dot on its end.
      const value = measure(y, chart.aggregate);
      return {
        spec: {
          ...base,
          layer: [
            { mark: { type: "rule" }, encoding: { y: scenarioAxis, x: value, x2: { datum: 0 }, color } },
            {
              mark: { type: "point", filled: true, size: 120, tooltip: true },
              encoding: { y: scenarioAxis, x: value, color },
            },
          ],
        },
      };
    }
    case "table": {
      const shown = [SCENARIO_NAME_FIELD, ...columns.map((column) => column.name)].slice(0, TABLE_COLUMNS);
      return {
        spec: {
          ...base,
          transform: [
            { window: [{ op: "row_number", as: "curio_row" }] },
            { filter: `datum.curio_row <= ${TABLE_ROWS}` },
            { fold: shown.map(vegaField), as: ["curio_column", "curio_cell"] },
          ],
          mark: { type: "text", align: "left", tooltip: true },
          encoding: {
            y: { field: "curio_row", type: "ordinal", axis: null },
            x: {
              field: "curio_column",
              type: "nominal",
              sort: shown,
              title: null,
              axis: { orient: "top", labelAngle: 0, domain: false, ticks: false },
            },
            text: { field: "curio_cell", type: "nominal" },
            color: { ...color, legend: null },
          },
        },
      };
    }
  }
}
