/**
 * Choosing a starter Vega-Lite spec from the shape of the incoming data.
 *
 * An unconnected node stays empty. Once an input actually arrives, and only
 * while the spec buffer is still empty, the editor fills with a complete,
 * readable spec chosen from the column types.
 *
 * **This is not the same mechanism as the geoshape injection in
 * `vegaGeoSpec.ts`, and the two must not be confused:**
 *
 * > Inject where the alternative is broken. Populate where the alternative is
 * > empty.
 *
 * `mark: "geoshape"` with no `shape` encoding is not under-specified, it is
 * *wrong*: vega-lite fits a projection to the raw row array and silently
 * renders NaN. That repair has one right answer, so it applies to any spec.
 * A blank editor is the opposite case: nothing is broken, so a guess costs
 * nothing and there is no user intent to override. Which is why what gets
 * written here is **explicit and complete**: it spells out the `shape` encoding
 * and `projection` rather than leaning on the injection. The node is a teaching
 * surface, and the user should see a spec they can read and edit, not a minimal
 * one that works by magic. The projection it spells out is the one the
 * injection would choose for the input (`geoProjection`), so a map in a
 * projected CRS such as EPSG:3395 draws, where mercator would draw nothing.
 *
 * Classification reads the payload's `schema` (pandas dtypes) rather than
 * sniffing values. Telling a date from a string, or a zip code from a
 * measurement, is exactly where sniffing goes wrong, and a wrong default locked
 * into the buffer is worse than no default at all.
 *
 * Pure, with no `vega` / `vega-lite` import, so it is testable under jest.
 */

import visDefaults from "../contracts/visDefaults.json";
import {
  classifyColumns,
  groupColumns,
  meetsRoles,
  type ClassifiedColumn,
  type ColumnRole,
} from "./starterSpec";
import { geoProjection, type GeoProjection } from "./vegaGeoSpec";

export interface DefaultSpecRule {
  /** Stable id, asserted in tests and named in docs/USAGE.md. */
  id: string;
  /** Does this rule apply? */
  when: (cols: Record<ColumnRole, string[]>) => boolean;
  /** The spec it produces; a map is drawn in *projection*, lon/lat's when none is given. */
  build: (cols: Record<ColumnRole, string[]>, projection?: GeoProjection) => Record<string, unknown>;
}

// No `data` block: the node replaces the root `data` with its own rows when
// it compiles the spec (useVega.compileGrammar), so one written here would
// only ever be overwritten.
const base = (rest: Record<string, unknown>) => ({
  $schema: visDefaults.vegaSchemaUrl,
  ...rest,
});

/**
 * Each rule's spec past its `mark`, by rule id. The rule itself (its place in
 * the ladder, the columns it needs and the mark it draws) is in
 * `vegaStarterLadder` of contracts/visDefaults.json, which the agents' shared
 * preamble states too; a test holds these ids to the ladder's, one builder per
 * rule.
 *
 * The bar rules state their `aggregate` rather than relying on vega-lite's
 * implicit behaviour, which silently overplots one bar per row. The map rules
 * write the projection they are given.
 */
export const VEGA_STARTER_BUILDERS: Readonly<
  Record<
    string,
    (c: Record<ColumnRole, string[]>, projection: GeoProjection) => Record<string, unknown>
  >
> = {
  "geometry+quantitative": (c, projection) => ({
    // Written out in full rather than relying on the geoshape injection:
    // the point of a default is to show the user what a spec looks like.
    projection,
    encoding: {
      shape: { field: c.geometry[0], type: "geojson" },
      color: { field: c.quantitative[0], type: "quantitative" },
    },
  }),
  geometry: (c, projection) => ({
    projection,
    encoding: { shape: { field: c.geometry[0], type: "geojson" } },
  }),
  "temporal+quantitative": (c) => ({
    encoding: {
      x: { field: c.temporal[0], type: "temporal" },
      y: { field: c.quantitative[0], type: "quantitative" },
    },
  }),
  "nominal+quantitative": (c) => ({
    encoding: {
      x: { field: c.nominal[0], type: "nominal" },
      y: { field: c.quantitative[0], type: "quantitative", aggregate: "mean" },
    },
  }),
  "two-quantitative": (c) => ({
    encoding: {
      x: { field: c.quantitative[0], type: "quantitative" },
      y: { field: c.quantitative[1], type: "quantitative" },
    },
  }),
  "one-quantitative": (c) => ({
    encoding: {
      x: { field: c.quantitative[0], type: "quantitative", bin: true },
      y: { aggregate: "count", type: "quantitative" },
    },
  }),
  "one-nominal": (c) => ({
    encoding: {
      x: { field: c.nominal[0], type: "nominal" },
      y: { aggregate: "count", type: "quantitative" },
    },
  }),
};

/**
 * The ladder: first match wins, in the file's order.
 *
 * The prose counterpart is the table in `docs/USAGE.md`. Adding or reordering a
 * rule trips `vegaDefaultSpec.test.ts`, which is there to point whoever does it
 * at that doc.
 */
export const DEFAULT_SPEC_RULES: DefaultSpecRule[] = visDefaults.vegaStarterLadder.map(
  (rule): DefaultSpecRule => ({
    id: rule.id,
    when: (c) => meetsRoles(c, rule.columns),
    // With no input to judge, the projection the injection gives such a map.
    build: (c, projection = geoProjection([])) =>
      base({ mark: rule.produces, ...VEGA_STARTER_BUILDERS[rule.id](c, projection) }),
  }),
);

/**
 * The spec for these columns, or `null` when nothing is usable. A map is
 * drawn in *projection*: the one the chart's draw gives its input
 * (`geoProjection`), lon/lat's when none is given.
 *
 * `null` rather than a half-built spec: an editor left empty is an honest
 * "nothing to suggest", while a spec referring to columns that are not there is
 * a puzzle the user has to undo.
 */
export function chooseDefaultSpec(
  columns: ClassifiedColumn[],
  projection?: GeoProjection,
): Record<string, unknown> | null {
  const grouped = groupColumns(columns);
  const rule = DEFAULT_SPEC_RULES.find((r) => r.when(grouped));
  return rule ? rule.build(grouped, projection) : null;
}

/** The chosen spec as the JSON text the editor should hold, or null. */
export function defaultSpecText(
  schema: Record<string, string> | null | undefined,
  sampleRows: any[] | null | undefined,
  geometryName?: string | null,
  projection?: GeoProjection,
): string | null {
  const spec = chooseDefaultSpec(classifyColumns(schema, sampleRows, geometryName), projection);
  return spec ? JSON.stringify(spec, null, 2) : null;
}
