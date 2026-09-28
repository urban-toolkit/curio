/**
 * Which column of a set of rows holds the geometry.
 *
 * Every grammar node that draws its input asks this the same way: the column
 * the payload declares, else the single geometry-valued column, else nobody
 * guesses and the candidates are handed back so the node can name them.
 */

const GEOJSON_GEOMETRY_TYPES = new Set([
  "Point",
  "MultiPoint",
  "LineString",
  "MultiLineString",
  "Polygon",
  "MultiPolygon",
  "GeometryCollection",
]);

function isObject(value: any): boolean {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

/** A GeoJSON *geometry* object (not a Feature, not a FeatureCollection). */
export function isGeoJsonGeometry(value: any): boolean {
  if (!isObject(value)) return false;
  if (!GEOJSON_GEOMETRY_TYPES.has(value.type)) return false;
  return value.coordinates !== undefined || value.geometries !== undefined;
}

/**
 * Which column to draw.
 *
 * 1. The payload declared one -- the active geometry column always wins.
 *    Secondary columns are addressed by name in their own layer, which is what
 *    drawing polygons and their centroids together needs anyway.
 * 2. Otherwise look for geometry-valued fields in the first non-empty row.
 *    Exactly one is unambiguous, so use it. (This is what lets a plain
 *    DataFrame carrying shapely objects work.)
 * 3. Zero or several: refuse to guess, and hand back the candidates so the
 *    caller can name them.
 */
export function resolveGeometryField(
  rows: any[],
  declaredName: string | null | undefined,
): { field: string | null; candidates: string[] } {
  if (declaredName) return { field: declaredName, candidates: [declaredName] };

  const sample = (Array.isArray(rows) ? rows : []).find((row) => isObject(row));
  if (!sample) return { field: null, candidates: [] };

  const candidates = Object.keys(sample).filter((key) => {
    const value = sample[key];
    if (isGeoJsonGeometry(value)) return true;
    // Already-wrapped Features count too, so a second pass is idempotent.
    return isObject(value) && value.type === "Feature" && value.geometry != null;
  });

  return { field: candidates.length === 1 ? candidates[0] : null, candidates };
}
