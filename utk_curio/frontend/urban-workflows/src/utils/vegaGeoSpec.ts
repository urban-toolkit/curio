/**
 * Making `{"mark": "geoshape"}` over a GeoDataFrame draw a map.
 *
 * The node does not ask "is this a GeoDataFrame?". It asks one question --
 * *which columns hold geometry, and what are they called?* -- and answers it
 * from the payload rather than by inference. Every geometry column keeps its
 * own pandas name, and one resolution rule with three outcomes covers the
 * matrix: use the declared column, or the single obvious one, or inject nothing
 * and say exactly what to type.
 *
 * Three findings shape all of this, none of them obvious:
 *
 * **A geojson-typed field must hold a `Feature`, not a bare geometry.**
 * vega-geo pushes the field value straight into `features[]` without wrapping
 * (`vega-geo/src/GeoJSON.js`), so d3-geo reads `features[i].geometry` and gets
 * `undefined`, giving empty bounds and `scale(NaN)`. Measured: bare geometry
 * renders `MNaN,NaN...` and nothing appears, with no error raised.
 *
 * **d3-geo wants clockwise exterior rings -- the inverse of RFC 7946 -- and
 * geopandas does not normalise.** A counter-clockwise ring renders as its own
 * complement: a sub-pixel polygon plus a full-height antimeridian subpath, i.e.
 * a blob over the whole viewport. shapely is inconsistent about this:
 * `convex_hull`, `buffer` and `dissolve` come out clockwise, but `envelope`
 * comes out counter-clockwise, so `gdf['bbox'] = gdf.envelope` -- an ordinary
 * teaching operation -- renders inverted. Hence `rewindRingsClockwise`.
 * `identity` is planar and winding-insensitive, so the rewind is skipped for
 * projected data.
 *
 * **Vega-Lite's implicit projection is wrong for projected coordinates, and
 * differs between unit and layer specs.** A unit spec with no `projection`
 * gets `equalEarth`; a layer spec emits no `type` at all and vega falls back to
 * mercator. On EPSG:3395 metres both produce NaN paths, while
 * `{type:'identity', reflectY:true}` renders exactly and still auto-fits. So an
 * explicit projection is injected in both cases. A top-level `projection`
 * reaches `layer` children but *not* `concat`/`facet`/`repeat` children, which
 * is why injection happens per unit while tracking the nearest declared
 * ancestor.
 *
 * Kept pure, with no `vega` / `vega-lite` import -- both are ESM-only and jest's
 * `transformIgnorePatterns` does not allow them through, so importing either
 * here would make this module untestable. Same constraint that produced
 * `vegaSpecSizing.ts`.
 */
import { detectCrs } from "./geoCrs";

/** Why a grammar node has nothing to draw. Mirrors `NodeEmptyReason`. */
export type GeoEmptyReason = "geometry-unresolved" | "geometry-ambiguous";

export type NormalizeGeoResult = {
  spec: any;
  emptyReason?: GeoEmptyReason;
  detail?: string;
};

const GEOJSON_GEOMETRY_TYPES = new Set([
  "Point",
  "MultiPoint",
  "LineString",
  "MultiLineString",
  "Polygon",
  "MultiPolygon",
  "GeometryCollection",
]);

/** Channels whose presence means vega-lite will build a projection. */
const PROJECTION_CHANNELS = ["longitude", "latitude", "longitude2", "latitude2"];

/** Container keys holding child specs. */
const CHILD_ARRAY_KEYS = ["layer", "concat", "vconcat", "hconcat"];

function isObject(value: any): boolean {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

/** A GeoJSON *geometry* object (not a Feature, not a FeatureCollection). */
function isGeoJsonGeometry(value: any): boolean {
  if (!isObject(value)) return false;
  if (!GEOJSON_GEOMETRY_TYPES.has(value.type)) return false;
  return value.coordinates !== undefined || value.geometries !== undefined;
}

/** The mark type, whether written as a string or an object. */
function markType(spec: any): string | null {
  const mark = spec?.mark;
  if (typeof mark === "string") return mark;
  if (isObject(mark) && typeof mark.type === "string") return mark.type;
  return null;
}

/**
 * Does this unit read from somewhere other than the node's own input?
 *
 * Not simply `unit.data != null`: every Curio spec declares
 * `"data": {"name": "data"}`, the named reference to the rows the node hands
 * vega. Treating that as a foreign source silently disabled injection for
 * essentially every real spec, while d3's tolerance for a `geometry`-shaped
 * datum made it *look* like it still worked. Only a `url` or inline `values`
 * means the unit brings its own data.
 */
function hasOwnData(unit: any): boolean {
  const data = unit?.data;
  if (!isObject(data)) return false;
  return data.url !== undefined || data.values !== undefined;
}

type UnitVisit = { unit: any; ancestorHasProjection: boolean };

/**
 * Collect leaf unit specs (anything with a `mark`), remembering whether any
 * ancestor already declared a `projection`.
 */
function collectUnits(
  spec: any,
  ancestorHasProjection: boolean,
  out: UnitVisit[],
): void {
  if (!isObject(spec)) return;

  if (spec.mark !== undefined) {
    out.push({ unit: spec, ancestorHasProjection });
    return;
  }

  // A declared `projection` reaches `layer` children, because vega-lite merges
  // `parentProjection` in `mapLayer` -- and *only* there. It never reaches
  // concat / facet / repeat children, so inheritance stops dead at those
  // boundaries rather than carrying on down.
  const layerInherits = ancestorHasProjection || spec.projection != null;

  if (Array.isArray(spec.layer)) {
    for (const child of spec.layer) collectUnits(child, layerInherits, out);
  }

  for (const key of CHILD_ARRAY_KEYS) {
    if (key === "layer") continue;
    const children = spec[key];
    if (Array.isArray(children)) {
      for (const child of children) collectUnits(child, false, out);
    }
  }
  // facet / repeat wrap a single child under `spec`.
  if (isObject(spec.spec)) collectUnits(spec.spec, false, out);
}

/**
 * True when the spec draws geometry, and therefore needs it on the wire.
 *
 * This is the payload gate. A spec that does not pass it never enters the geo
 * path at all and its `data.values` stays byte-identical to what it is today --
 * which matters because shipped dataflows chart multi-megabyte GeoJSON as bar
 * charts, and attaching geometry unconditionally would inline all of it and
 * re-ship it through `changeset()` on every brush.
 */
export function specNeedsGeometry(spec: any): boolean {
  const units: UnitVisit[] = [];
  collectUnits(spec, false, units);
  return units.some(({ unit }) => {
    if (markType(unit) === "geoshape") return true;
    const shape = unit?.encoding?.shape;
    return isObject(shape) && shape.type === "geojson";
  });
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

/** Twice the signed area of a ring; positive means counter-clockwise. */
function signedArea(ring: any[]): number {
  let area = 0;
  for (let i = 0, n = ring.length; i < n; i++) {
    const [x1, y1] = ring[i] ?? [];
    const [x2, y2] = ring[(i + 1) % n] ?? [];
    if (typeof x1 !== "number" || typeof y1 !== "number") continue;
    if (typeof x2 !== "number" || typeof y2 !== "number") continue;
    area += x1 * y2 - x2 * y1;
  }
  return area;
}

/**
 * Rewind polygon rings in place: exteriors clockwise, holes counter-clockwise.
 *
 * d3-geo's spherical winding convention is the inverse of RFC 7946's, and a
 * ring wound the wrong way renders as the complement of the shape it describes.
 * Measured on the 61 zip envelopes of the shipped Chicago boundary, which
 * `gdf.envelope` emits counter-clockwise: without the rewind the same layer
 * draws 122 subpaths and 17,770 path characters instead of 61 and 3,759, the
 * extra half being a full-height antimeridian subpath per box.
 *
 * "In place" reaches the payload, because rows share their geometry with it by
 * reference rather than copying. That is safe: the test is on the ring's actual
 * orientation, so rewinding an already-rewound ring is a no-op and repeated
 * parses of the same payload converge rather than flipping back and forth.
 */
export function rewindRingsClockwise(geometry: any): void {
  if (!isObject(geometry)) return;

  switch (geometry.type) {
    case "Polygon":
      rewindPolygon(geometry.coordinates);
      break;
    case "MultiPolygon":
      if (Array.isArray(geometry.coordinates)) {
        for (const polygon of geometry.coordinates) rewindPolygon(polygon);
      }
      break;
    case "GeometryCollection":
      if (Array.isArray(geometry.geometries)) {
        for (const child of geometry.geometries) rewindRingsClockwise(child);
      }
      break;
    default:
      break;
  }
}

function rewindPolygon(rings: any): void {
  if (!Array.isArray(rings)) return;
  rings.forEach((ring: any, index: number) => {
    if (!Array.isArray(ring)) return;
    const area = signedArea(ring);
    // Exterior ring (index 0) must be clockwise -> negative signed area.
    // Interior rings must be the opposite.
    const wantsCounterClockwise = index > 0;
    const isCounterClockwise = area > 0;
    if (isCounterClockwise !== wantsCounterClockwise) ring.reverse();
  });
}

/**
 * Resolve geometry for a spec, injecting what vega-lite needs and coercing the
 * values it will read. Mutates and returns `spec`.
 */
export function normalizeGeoSpec(
  spec: any,
  values: any[],
  opts: { geometryName?: string | null; crsName?: string | null } = {},
): NormalizeGeoResult {
  if (!isObject(spec)) return { spec };

  const units: UnitVisit[] = [];
  collectUnits(spec, false, units);
  if (units.length === 0) return { spec };

  const { field, candidates } = resolveGeometryField(values, opts.geometryName);

  const needsField = units.some(
    ({ unit }) => markType(unit) === "geoshape" && unit?.encoding?.shape == null,
  );

  if (needsField && field == null) {
    // Nothing is injected, and the caller renders a persistent node-body
    // message. A toast would decay and leave an unexplained blank node, which
    // is the exact complaint the empty-state work was filed about.
    if (candidates.length === 0) {
      return {
        spec,
        emptyReason: "geometry-unresolved",
        detail:
          'This spec uses mark: "geoshape", but the incoming data has no geometry column.',
      };
    }
    return {
      spec,
      emptyReason: "geometry-ambiguous",
      detail:
        `The incoming data has several geometry columns (${candidates.join(", ")}). ` +
        'Add "shape": {"field": "<name>", "type": "geojson"} to say which one to draw.',
    };
  }

  // --- Pass 2: inject shape and projection per unit ---------------------
  const projected = isProjected(values, field, opts.crsName);

  for (const { unit, ancestorHasProjection } of units) {
    const type = markType(unit);
    const isGeoshape = type === "geoshape";

    if (isGeoshape && field != null && unit.encoding?.shape == null && !hasOwnData(unit)) {
      unit.encoding = unit.encoding ?? {};
      unit.encoding.shape = { field, type: "geojson" };
    }

    const usesProjection =
      isGeoshape ||
      PROJECTION_CHANNELS.some((channel) => unit?.encoding?.[channel] != null);

    if (usesProjection && unit.projection == null && !ancestorHasProjection) {
      unit.projection = projected
        ? { type: "identity", reflectY: true }
        : { type: "mercator" };
    }
  }

  // --- Pass 3: coerce the values the geojson fields will read -----------
  const geoFields = new Set<string>();
  for (const { unit } of units) {
    const shape = unit?.encoding?.shape;
    if (isObject(shape) && shape.type === "geojson" && typeof shape.field === "string") {
      geoFields.add(shape.field);
    }
  }

  if (geoFields.size > 0 && Array.isArray(values)) {
    for (const row of values) {
      if (!isObject(row)) continue;
      for (const name of geoFields) {
        row[name] = coerceGeoValue(row[name], projected);
      }
    }
  }

  return { spec };
}

/**
 * Wrap a bare geometry as a Feature, and rewind its rings for geographic data.
 * Features, FeatureCollections, null and non-objects are left alone, so running
 * this twice is harmless.
 */
function coerceGeoValue(value: any, projected: boolean): any {
  if (!isObject(value)) return value;

  if (isGeoJsonGeometry(value)) {
    if (!projected) rewindRingsClockwise(value);
    return { type: "Feature", geometry: value };
  }

  if (value.type === "Feature" && value.geometry != null && !projected) {
    rewindRingsClockwise(value.geometry);
  }

  return value;
}

/** Sample the geometry actually being drawn to decide the projection. */
function isProjected(
  values: any[],
  field: string | null,
  crsName: string | null | undefined,
): boolean {
  const rows = Array.isArray(values) ? values : [];
  const geometries: any[] = [];

  for (const row of rows) {
    if (geometries.length >= 5) break;
    if (!isObject(row)) continue;
    const value = field != null ? row[field] : undefined;
    if (value == null) continue;
    geometries.push(isObject(value) && value.type === "Feature" ? value.geometry : value);
  }

  return detectCrs(crsName, geometries).projected;
}
