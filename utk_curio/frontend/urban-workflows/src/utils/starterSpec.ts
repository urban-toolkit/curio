/**
 * What a starter spec is chosen from, for every grammar node.
 *
 * The Vega-Lite and Autark nodes both fill an empty editor from the shape of
 * the input that arrived: each column gets a role, and each node's own ladder
 * turns the roles into a spec. The roles come from the payload's `schema`
 * (pandas dtypes) rather than from sniffing values, because telling a date from
 * a string, or a zip code from a measurement, is exactly where sniffing goes
 * wrong, and a wrong default locked into the buffer is worse than none.
 *
 * Pure, with no grammar import, so it is testable under jest.
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

/** Column names grouped by role, in the order they came. */
export function groupColumns(columns: ClassifiedColumn[]): Record<ColumnRole, string[]> {
  const out: Record<ColumnRole, string[]> = {
    geometry: [],
    temporal: [],
    quantitative: [],
    nominal: [],
  };
  for (const { name, role } of columns) out[role].push(name);
  return out;
}

/** Is the editor empty enough to fill without destroying anything? */
export function isEmptySpecBuffer(value: string | null | undefined): boolean {
  if (value == null) return true;
  const trimmed = value.trim();
  return trimmed === "" || trimmed === "{}";
}
