/**
 * What a Compare Scenarios node's Difference view (#662) draws from the node's
 * output, the difference (`utk_curio/sandbox/util/scenario_difference.py`):
 *
 * - two rasters' difference is a raster, which the view maps through the
 *   Autark node's map code, colored by one of its bands;
 * - two layers' difference is a layer joined on a stable id, mapped the same
 *   way, colored by one of its number columns or by `change` (added,
 *   removed, changed, unchanged);
 * - two tables' difference has no geometry to map, so the view shows it as a
 *   table through the Vega-Lite node's code, its rows colored by `change`.
 *
 * Pure, with no autk, `vega` or `vega-lite` import, so it is testable under jest.
 */
import { VEGA_SCHEMA_URL } from "../../generated/visDefaults";
import type { ClassifiedColumn } from "../starterSpec";
import { TABLE_COLUMNS, TABLE_ROWS, vegaField } from "./comparePresets";

/** The column a difference of layers or tables adds, and what it holds. */
export const CHANGE_FIELD = "change";
export const CHANGES = ["added", "removed", "changed", "unchanged"] as const;
export const CHANGE_COLORS = ["#2e8540", "#c0392b", "#b7791f", "#8a8f98"];

/**
 * The table the map reads the difference as, the node's output, named after
 * what the map colors it by: `<band or column>_change`, `change` for the
 * column of that name, and `difference` when nothing colors it. A table's name
 * is an SQL identifier in the map's database, so any other character becomes
 * `_`. The legend reads `differenceLegendTitle` instead.
 */
export function differenceTableName(value: DifferenceValue | undefined): string {
  if (!value) return "difference";
  const named = value.value === CHANGE_FIELD ? CHANGE_FIELD : `${value.value}_change`;
  const name = named.replace(/[^A-Za-z0-9_]/g, "_");
  return /^[A-Za-z_]/.test(name) ? name : `_${name}`;
}

/** The map's legend title (a layerRef's `legendTitle`): `<band or column> change`, or `change`. */
export function differenceLegendTitle(value: DifferenceValue): string {
  return value.value === CHANGE_FIELD ? CHANGE_FIELD : `${value.value} change`;
}

/**
 * A raster's or a layer's difference, from its lowest value (dark purple) to
 * its highest (yellow). Sequential, since autk-grammar takes no domain that
 * would centre a diverging scheme on zero.
 */
export const DIFFERENCE_INTERPOLATOR = "interpolateViridis";

export type DifferenceKind = "raster" | "layer" | "table";

export type DifferenceValue = { value: string; text: string; categorical: boolean };

/** The ids a difference joins rows on when the node names no key, the first both have
 * (`STABLE_IDS` in `utk_curio/sandbox/util/scenario_difference.py`). */
export const STABLE_IDS = ["osm_id", "building_id"] as const;

/**
 * The column a difference of layers or tables was joined on: the node's *key*,
 * else the first stable id its columns (*names*) hold.
 */
export function joinKey(names: readonly string[], key?: string): string | undefined {
  if (key && names.includes(key)) return key;
  return STABLE_IDS.find((id) => names.includes(id));
}

/**
 * What the map can color the difference by: a raster's bands, or a layer's
 * number columns but the ids its rows were joined on (*key*), and its
 * `change`.
 */
export function differenceValues(
  kind: DifferenceKind,
  read: { bands?: readonly string[]; columns?: readonly ClassifiedColumn[]; names?: readonly string[] },
  key?: string,
): DifferenceValue[] {
  if (kind === "raster") return (read.bands ?? []).map((band) => ({ value: band, text: band, categorical: false }));
  const names = read.names ?? [];
  const joined = joinKey(names, key);
  const numbers = (read.columns ?? [])
    .filter((column) => column.role === "quantitative" && column.name !== joined)
    .map((column) => ({ value: column.name, text: column.name, categorical: false }));
  const change = names.includes(CHANGE_FIELD)
    ? [{ value: CHANGE_FIELD, text: "change (added, removed, changed)", categorical: true }]
    : [];
  return [...numbers, ...change];
}

/** *wanted* when the difference has it, else its first value. */
export function resolveValue(wanted: string | undefined, values: readonly DifferenceValue[]): DifferenceValue | undefined {
  return values.find((option) => option.value === wanted) ?? values[0];
}

/**
 * The Autark document that draws the difference, one raster or layer colored
 * by *value*, read as the table `differenceTableName` names, its legend titled
 * by `differenceLegendTitle`.
 */
export function differenceMapDoc(value: DifferenceValue | undefined): Record<string, unknown> {
  const table = differenceTableName(value);
  if (!value) return { map: { layerRefs: [{ dataRef: table }] } };
  const legendTitle = differenceLegendTitle(value);
  if (value.categorical) {
    return {
      map: {
        layerRefs: [{
          dataRef: table,
          legendTitle,
          getFnv: value.value,
          getFnvType: "categorical",
          colorMapInterpolator: "schemeTableau10",
          colorMapDomain: [...CHANGES],
        }],
      },
    };
  }
  return {
    map: {
      layerRefs: [{
        dataRef: table,
        legendTitle,
        getFnv: value.value,
        getFnvType: "quantitative",
        colorMapInterpolator: DIFFERENCE_INTERPOLATOR,
      }],
    },
  };
}

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
