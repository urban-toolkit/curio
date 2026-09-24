/**
 * Working out the coordinate reference system of data arriving from geopandas.
 *
 * Two consumers need this and they want different answers from the same
 * evidence, so the evidence-gathering lives here once:
 *
 * - **autk-grammar** wants a `coordinateFormat` string for autk-db's
 *   `loadGeojson` (`detectCoordinateFormat`, unchanged in behaviour -- it was
 *   moved here rather than copied, because this repo already carries one silent
 *   near-duplicate of the Vega data path).
 * - **the Vega-Lite node** only needs to know *projected or not*, to choose
 *   between `{type:'identity', reflectY:true}` and `{type:'mercator'}`.
 *
 * The order matters. The EPSG urn that `parseOutput` re-injects is the only
 * reliable signal, but JavaScript has no EPSG table, so a code can only be
 * resolved *positively*: 4326 is known geographic, and anything else has to
 * fall through to the coordinate-magnitude heuristic rather than be guessed at.
 * 4269 (NAD83) is geographic and 3857 is not, and nothing in the number itself
 * says which.
 *
 * Kept pure, with no `vega` / `vega-lite` import, so it is testable under jest
 * -- see the note in `vegaSpecSizing.ts`.
 */

export type GeoCrs = {
  /** The EPSG code when the payload declared one, else null. */
  epsg: number | null;
  /** True when coordinates are in a projected (planar) system, not lon/lat. */
  projected: boolean;
};

/** Longitude/latitude bounds. Anything outside is not lon/lat. */
const WGS84_LON_MAX = 180;
const WGS84_LAT_MAX = 90;

/** How many geometries to look at before giving up on the magnitude test. */
const SAMPLE = 5;

/** EPSG codes we can positively resolve as geographic without a lookup table. */
const KNOWN_GEOGRAPHIC = new Set([4326]);

/**
 * The first `[x, y]` pair inside an arbitrarily nested coordinate array.
 *
 * Recurses into `GeometryCollection.geometries` as well as coordinate nesting:
 * a collection has no `coordinates` of its own, and bailing on it silently
 * yielded the wrong projection for the whole layer.
 */
export function firstCoordinate(coords: any): [number, number] | null {
  if (coords && typeof coords === "object" && !Array.isArray(coords)) {
    if (Array.isArray(coords.geometries)) {
      for (const geometry of coords.geometries) {
        const found = firstCoordinate(geometry);
        if (found) return found;
      }
      return null;
    }
    if (coords.coordinates !== undefined) return firstCoordinate(coords.coordinates);
    return null;
  }
  if (!Array.isArray(coords) || coords.length === 0) return null;
  if (typeof coords[0] === "number") return coords as [number, number];
  return firstCoordinate(coords[0]);
}

/** Parse an EPSG code out of a CRS urn, e.g. `urn:ogc:def:crs:EPSG::3395`. */
export function epsgFromCrsName(crsName: string | undefined | null): number | null {
  if (!crsName) return null;
  const match = crsName.match(/EPSG:{1,2}(\d+)/i);
  return match ? Number(match[1]) : null;
}

/**
 * Decide whether a set of geometries is in projected coordinates.
 *
 * `sampleGeometries` are GeoJSON geometry objects (or anything
 * `firstCoordinate` can walk). Taking geometries rather than a
 * FeatureCollection is what lets a plain DataFrame carrying shapely objects,
 * or a frame with no declared CRS at all, still pick a sensible projection.
 */
export function detectCrs(
  crsName: string | undefined | null,
  sampleGeometries: any[],
): GeoCrs {
  const epsg = epsgFromCrsName(crsName);

  // 1. A code we can resolve without guessing.
  if (epsg !== null && KNOWN_GEOGRAPHIC.has(epsg)) {
    return { epsg, projected: false };
  }

  // 2. Coordinate magnitude. Outside the lon/lat box it cannot be geographic.
  const geometries = Array.isArray(sampleGeometries) ? sampleGeometries : [];
  for (let i = 0; i < Math.min(geometries.length, SAMPLE); i++) {
    const coord = firstCoordinate(geometries[i]);
    if (!coord) continue;
    const [x, y] = coord;
    if (
      typeof x === "number" &&
      typeof y === "number" &&
      isFinite(x) &&
      isFinite(y) &&
      (Math.abs(x) > WGS84_LON_MAX || Math.abs(y) > WGS84_LAT_MAX)
    ) {
      return { epsg, projected: true };
    }
  }

  // 3. Nothing says otherwise: treat as lon/lat. Note this is where a projected
  // CRS with small coordinates near its false origin is misread -- strictly
  // better than the previous behaviour, which rendered nothing at all.
  return { epsg, projected: false };
}

/**
 * autk-db's `coordinateFormat` string for a FeatureCollection.
 *
 * Preserved exactly as it behaved inside `autkGrammarBehavior`, including
 * `EPSG:3395` as that module's stand-in for "projected" -- the specific code is
 * autk-local and means nothing to the Vega path.
 */
export function detectCoordinateFormat(fc: any): string {
  const crsName: string | undefined = fc?.crs?.properties?.name;
  const declared = epsgFromCrsName(crsName);
  if (declared !== null) return `EPSG:${declared}`;

  const geometries = (fc?.features ?? [])
    .slice(0, SAMPLE)
    .map((feature: any) => feature?.geometry)
    .filter(Boolean);

  return detectCrs(crsName, geometries).projected ? "EPSG:3395" : "EPSG:4326";
}
