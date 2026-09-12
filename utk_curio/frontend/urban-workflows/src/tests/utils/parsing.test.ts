/**
 * Getting geometry out of a geodataframe payload and into chart rows.
 *
 * `parseGeoDataframe` discarded the geometry in one line, which is why a
 * GeoDataFrame could never be drawn as a map without the user hand-writing a
 * converter in their Python node.
 */
import {
  parseGeoDataframe,
  parseGeoDataframeWithGeometry,
} from "../../utils/parsing";

const polygon = { type: "Polygon", coordinates: [[[0, 0], [0, 1], [1, 1], [0, 0]]] };

const payload = (overrides: any = {}) => ({
  type: "FeatureCollection",
  geometry_name: "geometry",
  features: [
    { type: "Feature", properties: { zip: "60601", pop: 2746 }, geometry: polygon },
  ],
  ...overrides,
});

describe("parseGeoDataframeWithGeometry", () => {
  test("attaches the geometry as a Feature under the declared name", () => {
    const { values, geometryName } = parseGeoDataframeWithGeometry(payload(), true);

    expect(geometryName).toBe("geometry");
    expect(values[0].zip).toBe("60601");
    expect(values[0].geometry).toEqual({ type: "Feature", geometry: polygon });
  });

  test("the Feature wrapper is not a copy", () => {
    // vega re-ships these rows through `changeset()` on every brush, so
    // copying coordinates here would be paid for repeatedly.
    const data = payload();
    const { values } = parseGeoDataframeWithGeometry(data, true);

    expect(values[0].geometry.geometry).toBe(data.features[0].geometry);
  });

  test("a renamed geometry column keeps its own name", () => {
    const data = payload({
      geometry_name: "geom",
      features: [{ properties: { zip: "60601" }, geometry: polygon }],
    });

    const { values } = parseGeoDataframeWithGeometry(data, true);

    expect(values[0].geom).toEqual({ type: "Feature", geometry: polygon });
    expect(values[0].geometry).toBeUndefined();
  });

  test("a string column called 'geometry' beside an active 'geom' is untouched", () => {
    // geopandas excludes the active column from `properties`, so the two can
    // never collide and no fallback name is needed.
    const data = payload({
      geometry_name: "geom",
      features: [
        { properties: { zip: "60601", geometry: "60601" }, geometry: polygon },
      ],
    });

    const { values } = parseGeoDataframeWithGeometry(data, true);

    expect(values[0].geometry).toBe("60601");
    expect(values[0].geom).toEqual({ type: "Feature", geometry: polygon });
  });

  test("a null geometry stays null rather than becoming an empty Feature", () => {
    // vega-lite emits an `isValid(datum[...])` filter ahead of the geojson
    // transform, which drops null rows cleanly.
    const data = payload({
      features: [{ properties: { zip: "60601" }, geometry: null }],
    });

    const { values } = parseGeoDataframeWithGeometry(data, true);

    expect(values[0].geometry).toBeNull();
  });

  test("no declared geometry column yields properties only", () => {
    const data = payload({
      geometry_name: null,
      features: [{ properties: { zip: "60601" }, geometry: null }],
    });

    const { values, geometryName } = parseGeoDataframeWithGeometry(data, true);

    expect(geometryName).toBeNull();
    expect(values[0]).toEqual({ zip: "60601" });
  });

  test("carries the declared CRS urn through", () => {
    const data = payload({
      crs: { type: "name", properties: { name: "urn:ogc:def:crs:EPSG::3395" } },
    });

    expect(parseGeoDataframeWithGeometry(data, true).crsName).toBe(
      "urn:ogc:def:crs:EPSG::3395",
    );
  });

  test("missing or empty features yield no rows", () => {
    expect(parseGeoDataframeWithGeometry({}, true).values).toEqual([]);
    expect(parseGeoDataframeWithGeometry({ features: [] }, true).values).toEqual([]);
  });
});

describe("parseGeoDataframe", () => {
  test("reproduces the properties-only shape exactly", () => {
    // Every non-geo chart still goes through this, so it must not move.
    expect(parseGeoDataframe(payload())).toEqual([{ zip: "60601", pop: 2746 }]);
  });

  test("withGeometry: false does not attach geometry", () => {
    const { values } = parseGeoDataframeWithGeometry(payload(), false);

    expect(values[0].geometry).toBeUndefined();
  });
});
