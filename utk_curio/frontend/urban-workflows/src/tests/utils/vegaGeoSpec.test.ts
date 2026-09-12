/**
 * Resolving geometry for a Vega-Lite spec.
 *
 * Tested as pure functions because `vega` and `vega-lite` are ESM and
 * unloadable under jest, and keeping this module free of them is what makes any of
 * it assertable.
 *
 * The two non-obvious properties, both measured against real renders:
 *
 * - a geojson-typed field must hold a **Feature**; a bare geometry gives d3-geo
 *   empty bounds and `scale(NaN)`, which draws nothing and raises nothing;
 * - d3-geo wants **clockwise** exterior rings, the inverse of RFC 7946, and a
 *   counter-clockwise ring renders as the complement of its own shape.
 */
import {
  normalizeGeoSpec,
  resolveGeometryField,
  rewindRingsClockwise,
  specNeedsGeometry,
} from "../../utils/vegaGeoSpec";

const CW = [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]];
const CCW = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]];

const geometry = (ring = CW) => ({ type: "Polygon", coordinates: [ring.map((p) => [...p])] });
const point = (x = 0.5, y = 0.5) => ({ type: "Point", coordinates: [x, y] });

const rows = (extra: any = {}) => [{ zip: "60601", geometry: geometry(), ...extra }];

describe("specNeedsGeometry", () => {
  test("a geoshape mark needs geometry, in string or object form", () => {
    expect(specNeedsGeometry({ mark: "geoshape" })).toBe(true);
    expect(specNeedsGeometry({ mark: { type: "geoshape", stroke: "#888" } })).toBe(true);
  });

  test("a geojson-typed shape encoding needs geometry", () => {
    expect(
      specNeedsGeometry({
        mark: "circle",
        encoding: { shape: { field: "centroid", type: "geojson" } },
      }),
    ).toBe(true);
  });

  test("ordinary charts do not", () => {
    // The payload gate. These specs must keep exactly today's `data.values`.
    expect(specNeedsGeometry({ mark: "bar" })).toBe(false);
    expect(specNeedsGeometry({ mark: "line", encoding: { x: { field: "t" } } })).toBe(false);
    expect(specNeedsGeometry({ vconcat: [{ mark: "bar" }, { mark: "point" }] })).toBe(false);
  });

  test("finds a geoshape nested in any container", () => {
    expect(specNeedsGeometry({ layer: [{ mark: "bar" }, { mark: "geoshape" }] })).toBe(true);
    expect(specNeedsGeometry({ hconcat: [{ mark: "geoshape" }] })).toBe(true);
    expect(specNeedsGeometry({ facet: {}, spec: { mark: "geoshape" } })).toBe(true);
  });
});

describe("resolveGeometryField", () => {
  test("the declared column wins", () => {
    expect(resolveGeometryField(rows(), "geometry").field).toBe("geometry");
  });

  test("exactly one geometry-valued column is used when none is declared", () => {
    // A plain DataFrame carrying shapely objects arrives this way.
    const { field } = resolveGeometryField([{ zip: "a", where: point() }], null);

    expect(field).toBe("where");
  });

  test("no geometry column resolves to nothing", () => {
    expect(resolveGeometryField([{ zip: "a", pop: 1 }], null)).toEqual({
      field: null,
      candidates: [],
    });
  });

  test("several candidates refuse to guess but name themselves", () => {
    const { field, candidates } = resolveGeometryField(
      [{ centroid: point(), bbox: geometry() }],
      null,
    );

    expect(field).toBeNull();
    expect(candidates).toEqual(["centroid", "bbox"]);
  });

  test("already-wrapped Features count as candidates", () => {
    const { field } = resolveGeometryField(
      [{ geom: { type: "Feature", geometry: geometry() } }],
      null,
    );

    expect(field).toBe("geom");
  });
});

describe("normalizeGeoSpec injection", () => {
  test("a bare geoshape gets both shape and projection", () => {
    const spec: any = { mark: "geoshape" };

    normalizeGeoSpec(spec, rows(), { geometryName: "geometry" });

    expect(spec.encoding.shape).toEqual({ field: "geometry", type: "geojson" });
    expect(spec.projection).toEqual({ type: "mercator" });
  });

  test("projected data gets identity + reflectY", () => {
    // On metres, both of vega-lite's implicit projections produce NaN paths.
    const spec: any = { mark: "geoshape" };
    const projectedRows = [
      { geometry: { type: "Polygon", coordinates: [[[-9755000, 5140000], [-9755000, 5141000], [-9754000, 5141000], [-9755000, 5140000]]] } },
    ];

    normalizeGeoSpec(spec, projectedRows, { geometryName: "geometry" });

    expect(spec.projection).toEqual({ type: "identity", reflectY: true });
  });

  test("an author's own shape encoding is never overwritten", () => {
    const spec: any = {
      mark: "geoshape",
      encoding: { shape: { field: "centroid", type: "geojson" } },
    };

    normalizeGeoSpec(spec, rows({ centroid: point() }), { geometryName: "geometry" });

    expect(spec.encoding.shape).toEqual({ field: "centroid", type: "geojson" });
  });

  test("an author's own projection is never overwritten", () => {
    const spec: any = { mark: "geoshape", projection: { type: "albersUsa" } };

    normalizeGeoSpec(spec, rows(), { geometryName: "geometry" });

    expect(spec.projection).toEqual({ type: "albersUsa" });
  });

  test("a layer parent's projection suppresses injection into its children", () => {
    const spec: any = {
      projection: { type: "albersUsa" },
      layer: [{ mark: "geoshape" }, { mark: "geoshape" }],
    };

    normalizeGeoSpec(spec, rows(), { geometryName: "geometry" });

    expect(spec.layer[0].projection).toBeUndefined();
    expect(spec.layer[1].projection).toBeUndefined();
  });

  test("an hconcat parent's projection does NOT reach its children", () => {
    // The non-obvious half: vega-lite merges `parentProjection` in `mapLayer`
    // only, so a top-level projection never reaches concat/facet/repeat
    // children. Injecting per unit is what covers both.
    const spec: any = {
      projection: { type: "albersUsa" },
      hconcat: [{ mark: "geoshape" }],
    };

    normalizeGeoSpec(spec, rows(), { geometryName: "geometry" });

    expect(spec.hconcat[0].projection).toEqual({ type: "mercator" });
  });

  test("the object mark form is detected", () => {
    const spec: any = { mark: { type: "geoshape", stroke: "#888" } };

    normalizeGeoSpec(spec, rows(), { geometryName: "geometry" });

    expect(spec.encoding.shape).toEqual({ field: "geometry", type: "geojson" });
  });

  test("longitude/latitude gets a projection but no shape", () => {
    const spec: any = {
      mark: "circle",
      encoding: { longitude: { field: "lon" }, latitude: { field: "lat" } },
    };

    normalizeGeoSpec(spec, [{ lon: -87, lat: 41 }], { geometryName: null });

    expect(spec.projection).toEqual({ type: "mercator" });
    expect(spec.encoding.shape).toBeUndefined();
  });

  test("a unit that brings its own data is left alone", () => {
    const spec: any = { mark: "geoshape", data: { url: "somewhere.json" } };

    normalizeGeoSpec(spec, rows(), { geometryName: "geometry" });

    expect(spec.encoding?.shape).toBeUndefined();
  });

  test('a named "data" reference means the node own rows, not a foreign source', () => {
    // Older specs carry an inert `"data": {"name": "data"}` block (the node
    // overwrites the root data with its own rows). Reading that as a separate
    // data source suppressed injection for every such spec -- and d3 is
    // tolerant enough of a `geometry`-shaped datum that it still drew
    // *something*, so the unit tests looked fine.
    const spec: any = { mark: "geoshape", data: { name: "data" } };

    normalizeGeoSpec(spec, rows(), { geometryName: "geometry" });

    expect(spec.encoding.shape).toEqual({ field: "geometry", type: "geojson" });
  });
});

describe("normalizeGeoSpec empty reasons", () => {
  test("no geometry at all reports geometry-unresolved and injects nothing", () => {
    const spec: any = { mark: "geoshape" };

    const result = normalizeGeoSpec(spec, [{ zip: "a", pop: 1 }], { geometryName: null });

    expect(result.emptyReason).toBe("geometry-unresolved");
    expect(spec.encoding?.shape).toBeUndefined();
    expect(spec.projection).toBeUndefined();
  });

  test("several candidates report geometry-ambiguous and name them", () => {
    const spec: any = { mark: "geoshape" };

    const result = normalizeGeoSpec(
      spec,
      [{ centroid: point(), bbox: geometry() }],
      { geometryName: null },
    );

    expect(result.emptyReason).toBe("geometry-ambiguous");
    expect(result.detail).toContain("centroid");
    expect(result.detail).toContain("bbox");
    expect(spec.encoding?.shape).toBeUndefined();
  });

  test("an explicit shape encoding means no reason is reported", () => {
    const spec: any = {
      mark: "geoshape",
      encoding: { shape: { field: "bbox", type: "geojson" } },
    };

    const result = normalizeGeoSpec(
      spec,
      [{ centroid: point(), bbox: geometry() }],
      { geometryName: null },
    );

    expect(result.emptyReason).toBeUndefined();
  });
});

describe("normalizeGeoSpec value coercion", () => {
  test("a bare geometry is wrapped as a Feature", () => {
    const values = rows();

    normalizeGeoSpec({ mark: "geoshape" }, values, { geometryName: "geometry" });

    expect(values[0].geometry.type).toBe("Feature");
    expect(values[0].geometry.geometry.type).toBe("Polygon");
  });

  test("an author-named secondary column is coerced too", () => {
    // Secondary geometry columns arrive as bare __geo_interface__ dicts.
    const values = rows({ centroid: point() });
    const spec: any = {
      mark: "geoshape",
      encoding: { shape: { field: "centroid", type: "geojson" } },
    };

    normalizeGeoSpec(spec, values, { geometryName: "geometry" });

    expect(values[0].centroid).toEqual({ type: "Feature", geometry: point() });
  });

  test("Features, nulls and non-objects are left alone", () => {
    const wrapped = { type: "Feature", geometry: geometry() };
    const values: any[] = [{ geometry: wrapped }, { geometry: null }, { geometry: "x" }];

    normalizeGeoSpec({ mark: "geoshape" }, values, { geometryName: "geometry" });

    expect(values[0].geometry).toBe(wrapped);
    expect(values[1].geometry).toBeNull();
    expect(values[2].geometry).toBe("x");
  });
});

describe("rewindRingsClockwise", () => {
  const isClockwise = (ring: number[][]) => {
    let area = 0;
    for (let i = 0; i < ring.length; i++) {
      const [x1, y1] = ring[i];
      const [x2, y2] = ring[(i + 1) % ring.length];
      area += x1 * y2 - x2 * y1;
    }
    return area < 0;
  };

  test("a counter-clockwise exterior ring is reversed", () => {
    // `gdf.envelope` produces exactly this, and without the rewind it renders
    // as a viewport-filling blob rather than a box.
    const geom = { type: "Polygon", coordinates: [CCW.map((p) => [...p])] };

    rewindRingsClockwise(geom);

    expect(isClockwise(geom.coordinates[0])).toBe(true);
  });

  test("a clockwise exterior ring is left alone", () => {
    const geom = { type: "Polygon", coordinates: [CW.map((p) => [...p])] };
    const before = JSON.parse(JSON.stringify(geom.coordinates[0]));

    rewindRingsClockwise(geom);

    expect(geom.coordinates[0]).toEqual(before);
  });

  test("interior rings get the opposite sense", () => {
    const geom = {
      type: "Polygon",
      coordinates: [CCW.map((p) => [...p]), CW.map((p) => [...p])],
    };

    rewindRingsClockwise(geom);

    expect(isClockwise(geom.coordinates[0])).toBe(true);
    expect(isClockwise(geom.coordinates[1])).toBe(false);
  });

  test("MultiPolygon is handled per part", () => {
    const geom = {
      type: "MultiPolygon",
      coordinates: [[CCW.map((p) => [...p])], [CCW.map((p) => [...p])]],
    };

    rewindRingsClockwise(geom);

    expect(isClockwise(geom.coordinates[0][0])).toBe(true);
    expect(isClockwise(geom.coordinates[1][0])).toBe(true);
  });

  test("non-polygon geometry is untouched", () => {
    const geom = point();

    expect(() => rewindRingsClockwise(geom)).not.toThrow();
    expect(geom).toEqual(point());
  });

  test("rewinding twice is a no-op", () => {
    // The rows share their geometry with the payload by reference, so the
    // rewind reaches it. That is only safe because it tests actual orientation
    // rather than flipping unconditionally -- otherwise a second parse of the
    // same payload would invert every polygon again.
    const geom = { type: "Polygon", coordinates: [CCW.map((p) => [...p])] };

    rewindRingsClockwise(geom);
    const once = JSON.parse(JSON.stringify(geom.coordinates[0]));
    rewindRingsClockwise(geom);

    expect(geom.coordinates[0]).toEqual(once);
  });

  test("the rewind is skipped for projected data", () => {
    // `identity` is planar and winding-insensitive, so it would be wasted work.
    const values = [
      {
        geometry: {
          type: "Polygon",
          coordinates: [[[-9755000, 5140000], [-9754000, 5140000], [-9754000, 5141000], [-9755000, 5140000]]],
        },
      },
    ];
    const before = JSON.parse(JSON.stringify(values[0].geometry.coordinates[0]));

    normalizeGeoSpec({ mark: "geoshape" }, values, { geometryName: "geometry" });

    expect((values[0].geometry as any).geometry.coordinates[0]).toEqual(before);
  });
});
