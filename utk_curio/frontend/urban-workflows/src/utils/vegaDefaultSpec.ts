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

export type ColumnRole = "geometry" | "temporal" | "quantitative" | "nominal";

export interface ClassifiedColumn {
  name: string;
  role: ColumnRole;
}

/** Positional row index Curio stamps onto every row; never a chart field. */
const ROW_INDEX = "__row_index__";

/** Columns Curio adds or uses for bookkeeping, never worth charting. */
const RESERVED = new Set([ROW_INDEX, "interacted"]);

/**
 * Below this many rows, "every value is distinct" says nothing.
 *
 * A two-row sample makes every nominal column look like an identifier, which
 * would throw away the very column the chart should be grouped by. The preview
 * endpoint returns 100 rows, so real data is never near this floor.
 */
const ID_HEURISTIC_MIN_ROWS = 10;

function roleForDtype(dtype: string): ColumnRole | null {
  const d = dtype.toLowerCase();
  if (d === "geometry") return "geometry";
  if (d.startsWith("datetime") || d.startsWith("period") || d.startsWith("timedelta")) {
    return "temporal";
  }
  if (d.startsWith("int") || d.startsWith("uint") || d.startsWith("float")) {
    return "quantitative";
  }
  // `str` is pandas 3's dtype for a string column; pandas 2 said `object`.
  if (d === "bool" || d === "object" || d === "str" || d === "string" || d === "category") {
    return "nominal";
  }
  return null;
}

/** Value-sniffing fallback, for inline data or a payload with no `schema`. */
function roleForValue(value: unknown): ColumnRole | null {
  if (value == null) return null;
  if (typeof value === "number") return Number.isFinite(value) ? "quantitative" : null;
  if (typeof value === "boolean") return "nominal";
  if (typeof value === "object") {
    const type = (value as any).type;
    return type === "Feature" || typeof type === "string" ? "geometry" : null;
  }
  if (typeof value === "string") return "nominal";
  return null;
}

/**
 * Assign a role to every usable column.
 *
 * Nominal columns whose every value is distinct are dropped: a column with one
 * value per row is an identifier, and charting it produces one bar per row,
 * which is noise rather than a starting point.
 */
export function classifyColumns(
  schema: Record<string, string> | null | undefined,
  sampleRows: any[] | null | undefined,
  geometryName?: string | null,
): ClassifiedColumn[] {
  const rows = Array.isArray(sampleRows) ? sampleRows : [];
  const sample = rows.find((row) => row && typeof row === "object") ?? {};
  const names = schema ? Object.keys(schema) : Object.keys(sample);
  // The active geometry column is *named* by the payload rather than carried
  // in its rows: a FeatureCollection keeps that geometry on the feature, so it
  // never appears among the property keys a sample row exposes. Without this a
  // GeoDataFrame that arrives without a schema reads as having no geometry.
  if (geometryName && !names.includes(geometryName)) names.push(geometryName);

  const columns: ClassifiedColumn[] = [];
  for (const name of names) {
    if (RESERVED.has(name)) continue;

    let role =
      name === geometryName
        ? ("geometry" as ColumnRole)
        : schema
          ? roleForDtype(schema[name])
          : roleForValue(sample[name]);

    if (role == null) continue;

    if (role === "nominal" && rows.length >= ID_HEURISTIC_MIN_ROWS) {
      const seen = new Set(rows.map((row) => row?.[name]));
      if (seen.size === rows.length) continue; // an identifier
    }

    columns.push({ name, role });
  }

  return columns;
}

export interface DefaultSpecRule {
  /** Stable id, asserted in tests and named in docs/USAGE.md. */
  id: string;
  /** Does this rule apply? */
  when: (cols: Record<ColumnRole, string[]>) => boolean;
  /** The spec it produces. */
  build: (cols: Record<ColumnRole, string[]>) => Record<string, unknown>;
}

const SCHEMA_URL = "https://vega.github.io/schema/vega-lite/v6.json";

// No `data` block: the node replaces the root `data` with its own rows when
// it compiles the spec (useVega.compileGrammar), so one written here would
// only ever be overwritten.
const base = (rest: Record<string, unknown>) => ({
  $schema: SCHEMA_URL,
  ...rest,
});

/**
 * The ladder: first match wins.
 *
 * The prose counterpart is the table in `docs/USAGE.md`. Adding or reordering a
 * rule trips `vegaDefaultSpec.test.ts`, which is there to point whoever does it
 * at that doc.
 *
 * The bar rules state their `aggregate` rather than relying on vega-lite's
 * implicit behaviour, which silently overplots one bar per row.
 */
export const DEFAULT_SPEC_RULES: DefaultSpecRule[] = [
  {
    id: "geometry+quantitative",
    when: (c) => c.geometry.length > 0 && c.quantitative.length > 0,
    build: (c) =>
      base({
        // Written out in full rather than relying on the geoshape injection:
        // the point of a default is to show the user what a spec looks like.
        mark: "geoshape",
        projection: { type: "mercator" },
        encoding: {
          shape: { field: c.geometry[0], type: "geojson" },
          color: { field: c.quantitative[0], type: "quantitative" },
        },
      }),
  },
  {
    id: "geometry",
    when: (c) => c.geometry.length > 0,
    build: (c) =>
      base({
        mark: "geoshape",
        projection: { type: "mercator" },
        encoding: { shape: { field: c.geometry[0], type: "geojson" } },
      }),
  },
  {
    id: "temporal+quantitative",
    when: (c) => c.temporal.length > 0 && c.quantitative.length > 0,
    build: (c) =>
      base({
        mark: "line",
        encoding: {
          x: { field: c.temporal[0], type: "temporal" },
          y: { field: c.quantitative[0], type: "quantitative" },
        },
      }),
  },
  {
    id: "nominal+quantitative",
    when: (c) => c.nominal.length > 0 && c.quantitative.length > 0,
    build: (c) =>
      base({
        mark: "bar",
        encoding: {
          x: { field: c.nominal[0], type: "nominal" },
          y: { field: c.quantitative[0], type: "quantitative", aggregate: "mean" },
        },
      }),
  },
  {
    id: "two-quantitative",
    when: (c) => c.quantitative.length >= 2,
    build: (c) =>
      base({
        mark: "point",
        encoding: {
          x: { field: c.quantitative[0], type: "quantitative" },
          y: { field: c.quantitative[1], type: "quantitative" },
        },
      }),
  },
  {
    id: "one-quantitative",
    when: (c) => c.quantitative.length === 1,
    build: (c) =>
      base({
        mark: "bar",
        encoding: {
          x: { field: c.quantitative[0], type: "quantitative", bin: true },
          y: { aggregate: "count", type: "quantitative" },
        },
      }),
  },
  {
    id: "one-nominal",
    when: (c) => c.nominal.length > 0,
    build: (c) =>
      base({
        mark: "bar",
        encoding: {
          x: { field: c.nominal[0], type: "nominal" },
          y: { aggregate: "count", type: "quantitative" },
        },
      }),
  },
];

function group(columns: ClassifiedColumn[]): Record<ColumnRole, string[]> {
  const out: Record<ColumnRole, string[]> = {
    geometry: [],
    temporal: [],
    quantitative: [],
    nominal: [],
  };
  for (const { name, role } of columns) out[role].push(name);
  return out;
}

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
  const grouped = group(columns);
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

/** Is the editor empty enough to fill without destroying anything? */
export function isEmptySpecBuffer(value: string | null | undefined): boolean {
  if (value == null) return true;
  const trimmed = value.trim();
  return trimmed === "" || trimmed === "{}";
}
