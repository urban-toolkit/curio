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
 * one that works by magic.
 *
 * Classification reads the payload's `schema` (pandas dtypes) rather than
 * sniffing values. Telling a date from a string, or a zip code from a
 * measurement, is exactly where sniffing goes wrong, and a wrong default locked
 * into the buffer is worse than no default at all.
 *
 * Pure, with no `vega` / `vega-lite` import, so it is testable under jest.
 */

import {
  VEGA_SCHEMA_URL,
  VEGA_STARTER_LADDER,
  type VegaStarterRuleId,
} from "../generated/visDefaults";
import {
  classifyColumns,
  groupColumns,
  meetsRoles,
  type ClassifiedColumn,
  type ColumnRole,
} from "./starterSpec";

export interface DefaultSpecRule {
  /** Stable id, asserted in tests and named in docs/USAGE.md. */
  id: string;
  /** Does this rule apply? */
  when: (cols: Record<ColumnRole, string[]>) => boolean;
  /** The spec it produces. */
  build: (cols: Record<ColumnRole, string[]>) => Record<string, unknown>;
}

// No `data` block: the node replaces the root `data` with its own rows when
// it compiles the spec (useVega.compileGrammar), so one written here would
// only ever be overwritten.
const base = (rest: Record<string, unknown>) => ({
  $schema: VEGA_SCHEMA_URL,
  ...rest,
});

/**
 * Each rule's spec past its `mark`, by rule id. The rule itself (its place in
 * the ladder, the columns it needs and the mark it draws) is generated into
 * `VEGA_STARTER_LADDER`, which the agents' shared preamble states too.
 *
 * The bar rules state their `aggregate` rather than relying on vega-lite's
 * implicit behaviour, which silently overplots one bar per row.
 */
export const VEGA_STARTER_BUILDERS: Record<
  VegaStarterRuleId,
  (c: Record<ColumnRole, string[]>) => Record<string, unknown>
> = {
  "geometry+quantitative": (c) => ({
    // Written out in full rather than relying on the geoshape injection:
    // the point of a default is to show the user what a spec looks like.
    projection: { type: "mercator" },
    encoding: {
      shape: { field: c.geometry[0], type: "geojson" },
      color: { field: c.quantitative[0], type: "quantitative" },
    },
  }),
  geometry: (c) => ({
    projection: { type: "mercator" },
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
 * The ladder: first match wins, in the generated order.
 *
 * The prose counterpart is the table in `docs/USAGE.md`. Adding or reordering a
 * rule trips `vegaDefaultSpec.test.ts`, which is there to point whoever does it
 * at that doc.
 */
export const DEFAULT_SPEC_RULES: DefaultSpecRule[] = VEGA_STARTER_LADDER.map(
  (rule): DefaultSpecRule => ({
    id: rule.id,
    when: (c) => meetsRoles(c, rule.columns),
    build: (c) => base({ mark: rule.produces, ...VEGA_STARTER_BUILDERS[rule.id](c) }),
  }),
);

/**
 * The spec for these columns, or `null` when nothing is usable.
 *
 * `null` rather than a half-built spec: an editor left empty is an honest
 * "nothing to suggest", while a spec referring to columns that are not there is
 * a puzzle the user has to undo.
 */
export function chooseDefaultSpec(
  columns: ClassifiedColumn[],
): Record<string, unknown> | null {
  const grouped = groupColumns(columns);
  const rule = DEFAULT_SPEC_RULES.find((r) => r.when(grouped));
  return rule ? rule.build(grouped) : null;
}

/** The chosen spec as the JSON text the editor should hold, or null. */
export function defaultSpecText(
  schema: Record<string, string> | null | undefined,
  sampleRows: any[] | null | undefined,
  geometryName?: string | null,
): string | null {
  const spec = chooseDefaultSpec(classifyColumns(schema, sampleRows, geometryName));
  return spec ? JSON.stringify(spec, null, 2) : null;
}
