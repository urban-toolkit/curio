/**
 * #443: what a preview cell shows for an object. A geometry reads as WKT in
 * the form shapely's `.wkt` writes it, which is what the server's catalog
 * preview shows for the same value (`sandbox/util/tabular_preview._as_wkt`).
 */
import { cellText, geojsonToWkt } from "../../utils/cellText";

describe("geojsonToWkt", () => {
  test.each([
    [{ type: "Point", coordinates: [0.67, 0.33] }, "POINT (0.67 0.33)"],
    [{ type: "Point", coordinates: [1, 2, 3] }, "POINT Z (1 2 3)"],
    [{ type: "LineString", coordinates: [[0, 0], [1, 1]] }, "LINESTRING (0 0, 1 1)"],
    [{ type: "MultiPoint", coordinates: [[0, 0], [1, 1]] }, "MULTIPOINT ((0 0), (1 1))"],
    [
      { type: "Polygon", coordinates: [[[0, 0], [2, 0], [2, 2], [0, 0]], [[0.5, 0.5], [1, 0.5], [1, 1], [0.5, 0.5]]] },
      "POLYGON ((0 0, 2 0, 2 2, 0 0), (0.5 0.5, 1 0.5, 1 1, 0.5 0.5))",
    ],
    [
      { type: "MultiLineString", coordinates: [[[0, 0], [1, 1]], [[2, 2], [3, 3]]] },
      "MULTILINESTRING ((0 0, 1 1), (2 2, 3 3))",
    ],
    [
      { type: "MultiPolygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]], [[[5, 5], [6, 5], [6, 6], [5, 5]]]] },
      "MULTIPOLYGON (((0 0, 1 0, 1 1, 0 0)), ((5 5, 6 5, 6 6, 5 5)))",
    ],
    [
      { type: "GeometryCollection", geometries: [{ type: "Point", coordinates: [0, 0] }, { type: "LineString", coordinates: [[0, 0], [1, 1]] }] },
      "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (0 0, 1 1))",
    ],
    [{ type: "Point", coordinates: [] }, "POINT EMPTY"],
    [{ type: "GeometryCollection", geometries: [] }, "GEOMETRYCOLLECTION EMPTY"],
  ])("%j", (geometry, wkt) => {
    expect(geojsonToWkt(geometry)).toBe(wkt);
  });

  test.each([
    [{ type: "Feature", geometry: { type: "Point", coordinates: [0, 0] } }],
    [{ type: "Point" }],
    [{ type: "Point", coordinates: ["a", "b"] }],
    [{ type: "LineString", coordinates: [[0, 0], "x"] }],
    [{ CurbRamp: 1.93 }],
    [[1, 2]],
    ["POINT (1 2)"],
  ])("%j is not a geometry", (value) => {
    expect(geojsonToWkt(value)).toBeNull();
  });
});

describe("cellText", () => {
  test("objects that are not geometries read as JSON", () => {
    expect(cellText({ CurbRamp: 1.93 })).toBe('{"CurbRamp":1.93}');
    expect(cellText([1, 2])).toBe("[1,2]");
  });

  test("scalars read as String() reads them", () => {
    expect(cellText(3.5)).toBe("3.5");
    expect(cellText(true)).toBe("true");
    expect(cellText("text")).toBe("text");
  });

  test("a circular object still reads as something", () => {
    const a: Record<string, unknown> = {};
    a.self = a;
    expect(cellText(a)).toBe("[object Object]");
  });
});
