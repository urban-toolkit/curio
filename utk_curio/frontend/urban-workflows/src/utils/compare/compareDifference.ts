/**
 * What a Compare Scenarios node's Difference view (#662) shows of the node's
 * output, the difference (`utk_curio/sandbox/util/scenario_difference.py`):
 *
 * - two rasters' difference is a raster, and two layers' difference is a
 *   layer joined on a stable id: an Autark node after the node draws either
 *   on a map;
 * - two tables' difference has no geometry to map, so the view shows it as a
 *   table through the Vega-Lite node's code, its rows colored by `change`
 *   (added, removed, changed, unchanged).
 *
 * Pure, with no `vega` or `vega-lite` import, so it is testable under jest.
 */
import { VEGA_SCHEMA_URL } from "../../generated/visDefaults";
import { TABLE_COLUMNS, TABLE_ROWS, vegaField } from "./comparePresets";

/** The column a difference of layers or tables adds, and what it holds. */
export const CHANGE_FIELD = "change";
export const CHANGES = ["added", "removed", "changed", "unchanged"] as const;
export const CHANGE_COLORS = ["#2e8540", "#c0392b", "#b7791f", "#8a8f98"];

export type DifferenceKind = "raster" | "layer" | "table";

/**
 * The Vega-Lite table a difference of two tables is shown as: its first rows
 * and its first columns (*names*, in its order), each row in the color of its
 * `change`.
 */
export function differenceTableSpec(names: readonly string[]): Record<string, unknown> {
  const shown = names.slice(0, TABLE_COLUMNS);
  return {
    $schema: VEGA_SCHEMA_URL,
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
      color: {
        field: CHANGE_FIELD,
        type: "nominal",
        title: "Change",
        scale: { domain: [...CHANGES], range: CHANGE_COLORS },
      },
    },
  };
}

/**
 * Whether the node's output is a difference: a raster, or a layer or a table
 * whose columns (*names*) hold `change`. Until the node runs again after a
 * switch from Chart, its output is the stacked table, which is not.
 */
export function isDifference(kind: DifferenceKind | "other", names: readonly string[]): boolean {
  if (kind === "raster") return true;
  if (kind === "other") return false;
  return names.includes(CHANGE_FIELD);
}
