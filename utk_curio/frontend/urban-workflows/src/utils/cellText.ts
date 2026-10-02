/**
 * What a preview table shows for one value.
 *
 * Rows built in the browser (the Data Pool reads a GeoJSON FeatureCollection)
 * carry a property's dict, list or secondary geometry as an object, which
 * `String()` prints as "[object Object]". A geometry reads as WKT, as the
 * server's catalog preview writes it (`sandbox/util/tabular_preview._as_wkt`,
 * shapely's `.wkt`); any other object as JSON.
 */

const WKT_TAG: Record<string, string> = {
  Point: "POINT",
  MultiPoint: "MULTIPOINT",
  LineString: "LINESTRING",
  MultiLineString: "MULTILINESTRING",
  Polygon: "POLYGON",
  MultiPolygon: "MULTIPOLYGON",
  GeometryCollection: "GEOMETRYCOLLECTION",
};

class NotAGeometry extends Error {}

function position(p: unknown): string {
  if (!Array.isArray(p) || p.length < 2 || !p.every((n) => typeof n === "number" && Number.isFinite(n))) {
    throw new NotAGeometry();
  }
  return p.join(" ");
}

const list = <T,>(items: unknown, each: (item: unknown) => T): T[] => {
  if (!Array.isArray(items)) throw new NotAGeometry();
  return items.map(each);
};

/** `(x y, x y)`: a line or a ring. */
const path = (ps: unknown) => `(${list(ps, position).join(", ")})`;

/** The first position of nested coordinate arrays, to tell 2D from 3D. */
function firstPosition(c: unknown): unknown[] | null {
  let cur: unknown = c;
  while (Array.isArray(cur) && Array.isArray(cur[0])) cur = cur[0];
  return Array.isArray(cur) && cur.length > 0 ? cur : null;
}

function body(type: string, c: unknown): string {
  switch (type) {
    case "Point":
      return `(${position(c)})`;
    case "LineString":
      return path(c);
    case "MultiPoint":
      return `(${list(c, (p) => `(${position(p)})`).join(", ")})`;
    case "Polygon":
    case "MultiLineString":
      return `(${list(c, path).join(", ")})`;
    case "MultiPolygon":
      return `(${list(c, (poly) => `(${list(poly, path).join(", ")})`).join(", ")})`;
    default:
      throw new NotAGeometry();
  }
}

/** A GeoJSON geometry as WKT, or null when `value` is not one. */
export function geojsonToWkt(value: unknown): string | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const g = value as { type?: unknown; coordinates?: unknown; geometries?: unknown };
  const tag = typeof g.type === "string" ? WKT_TAG[g.type] : undefined;
  if (!tag) return null;
  try {
    if (g.type === "GeometryCollection") {
      const parts = list(g.geometries, (part) => {
        const wkt = geojsonToWkt(part);
        if (wkt === null) throw new NotAGeometry();
        return wkt;
      });
      return parts.length ? `${tag} (${parts.join(", ")})` : `${tag} EMPTY`;
    }
    if (!Array.isArray(g.coordinates)) return null;
    if (g.coordinates.length === 0) return `${tag} EMPTY`;
    const first = firstPosition(g.coordinates);
    const z = first && first.length >= 3 ? " Z" : "";
    return `${tag}${z} ${body(g.type as string, g.coordinates)}`;
  } catch (err) {
    if (err instanceof NotAGeometry) return null;
    throw err;
  }
}

/** The text a preview cell shows for `value` (null and undefined are the caller's). */
export function cellText(value: unknown): string {
  if (value !== null && typeof value === "object") {
    const wkt = geojsonToWkt(value);
    if (wkt !== null) return wkt;
    try {
      const json = JSON.stringify(value);
      if (json !== undefined) return json;
    } catch {
      // A circular structure has no JSON; String() still says something.
    }
  }
  return String(value);
}
