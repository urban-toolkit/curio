/**
 * A Vega-Lite node comparing scenarios: its Compare scenarios switch, saved at
 * `metadata.vegaCompare`. With it on, each input circle is one scenario, as
 * many as are wired, and the spec reads them stacked as one table,
 * `scenarios`, each row carrying its scenario (`SCENARIO_COLUMNS`). The labels
 * are utils/compare/compareInputs': the
 * scenario the input's node is in, else the node's name in a neutral color.
 *
 * An encoding on the scenario that sets no scale of its own is given the
 * scenarios' colors, so `"color": {"field": "scenario_name"}` draws each in
 * its color on the canvas, and in circle order on an axis or a facet.
 *
 * What the spec reads of each scenario (utils/vegaSpecFields) is checked
 * against the columns its input has, for the node to say what one lacks.
 *
 * Pure, and no `vega-lite` import, so it stays testable under jest.
 */
import type { CompareInputLabel } from "./compare/compareInputs";
import { specFields } from "./vegaSpecFields";

export interface VegaCompareSettings {
  enabled: boolean;
}

/** The dataset the stacked scenarios are. */
export const SCENARIOS_DATASET = "scenarios";

/** The columns the node adds to every row. */
export const SCENARIO_COLUMNS = ["scenario", "scenario_name", "scenario_color", "scenario_order"] as const;

/** A wired circle and the scenario it is. */
export interface ScenarioInput {
  slot: number;
  label: CompareInputLabel;
}

/** What one circle's input lacks of what the spec reads. */
export interface ScenarioRequirement extends ScenarioInput {
  /** Its input's columns, or null before it has arrived. */
  columns: string[] | null;
  missing: string[];
}

const isObject = (value: unknown): value is Record<string, any> =>
  value != null && typeof value === "object" && !Array.isArray(value);

/** The switch, or undefined when it is off (so a dataflow without one serializes as before). */
export function normalizeVegaCompare(raw: unknown): VegaCompareSettings | undefined {
  return isObject(raw) && raw.enabled === true ? { enabled: true } : undefined;
}

export const isComparing = (data: unknown): boolean =>
  isObject(data) && normalizeVegaCompare(data.vegaCompare) !== undefined;

/** The dataset `input_<slot>`'s circle. */
const slotOf = (name: string): number => {
  const match = /^input_(\d+)$/.exec(name);
  return match ? Number(match[1]) : -1;
};

/**
 * The inputs' rows as one table, in circle order, each row under its
 * scenario. An input with no label (none wired) is named by its circle.
 */
export function stackScenarios(
  datasets: readonly { name: string; values: any[] }[],
  inputs: readonly ScenarioInput[],
): { name: string; values: any[] } {
  const bySlot = new Map(inputs.map((input) => [input.slot, input.label]));
  const values = datasets
    .map((dataset) => ({ dataset, slot: slotOf(dataset.name) }))
    .filter(({ slot }) => slot >= 0)
    .sort((a, b) => a.slot - b.slot)
    .flatMap(({ dataset, slot }, order) => {
      const label = bySlot.get(slot);
      const name = label?.name ?? dataset.name;
      return (Array.isArray(dataset.values) ? dataset.values : []).map((row) => ({
        ...(isObject(row) ? row : { value: row }),
        scenario: label?.scenario ?? name,
        scenario_name: name,
        scenario_color: label?.color,
        scenario_order: order,
      }));
    });
  return { name: SCENARIOS_DATASET, values };
}

const COLOR_CHANNELS = new Set(["color", "fill", "stroke"]);
const ORDER_CHANNELS = new Set(["x", "y", "xOffset", "yOffset", "row", "column", "facet", "shape"]);

/**
 * *spec*, in place: the stacked scenarios its default data, and each encoding
 * on the scenario given the scenarios' colors (a color channel) or their
 * circle order (an axis, an offset, a facet), unless it sets its own.
 */
export function applyScenarioDefaults(spec: any, inputs: readonly ScenarioInput[]): any {
  if (!isObject(spec)) return spec;
  if (spec.data === undefined) spec.data = { name: SCENARIOS_DATASET };
  const ordered = [...inputs].sort((a, b) => a.slot - b.slot);
  const names = ordered.map((input) => input.label.name);
  const ids = ordered.map((input) => input.label.scenario ?? input.label.name);
  const colors = ordered.map((input) => input.label.color);
  const domain = (field: string) => (field === "scenario" ? ids : names);
  const visit = (node: unknown) => {
    if (Array.isArray(node)) return node.forEach(visit);
    if (!isObject(node)) return;
    for (const [key, value] of Object.entries(node)) {
      if (key === "data" || key === "datasets") continue;
      const onScenario = isObject(value) && (value.field === "scenario" || value.field === "scenario_name");
      if (onScenario && COLOR_CHANNELS.has(key) && value.scale === undefined) {
        value.scale = { domain: domain(value.field), range: colors };
      } else if (onScenario && ORDER_CHANNELS.has(key) && value.sort === undefined) {
        value.sort = domain(value.field);
      }
      visit(value);
    }
  };
  visit(spec);
  return spec;
}

/** The columns *spec* asks of each scenario: what it reads, less the node's own. */
export function requiredColumns(spec: unknown): string[] {
  const own = new Set<string>([...SCENARIO_COLUMNS, "__input__", "__row_index__"]);
  return specFields(spec).filter((field) => !own.has(field));
}

/** For each wired circle, what of *required* its input lacks. */
export function scenarioRequirements(
  inputs: readonly ScenarioInput[],
  required: readonly string[],
  columnsBySlot: ReadonlyMap<number, string[]>,
): ScenarioRequirement[] {
  return inputs.map((input) => {
    const columns = columnsBySlot.get(input.slot) ?? null;
    const have = new Set(columns ?? []);
    return { ...input, columns, missing: columns === null ? [] : required.filter((field) => !have.has(field)) };
  });
}

/**
 * The starter spec of a node comparing scenarios: its first number per
 * scenario, as bars. It names no data, so it reads the stacked scenarios while
 * the node compares them and its first input when it does not.
 */
export function compareStarterSpec(numberColumn: string | null): string | null {
  if (!numberColumn) return null;
  return JSON.stringify({
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    mark: { type: "bar", tooltip: true },
    encoding: {
      x: { field: "scenario_name", type: "nominal", title: null, axis: { labelAngle: 0 } },
      y: { field: numberColumn, type: "quantitative", aggregate: "mean", title: numberColumn },
      color: { field: "scenario_name", type: "nominal", legend: null },
    },
  }, null, 2);
}
