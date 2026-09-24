/**
 * Deciding whether geopandas data is projected or lon/lat.
 *
 * The whole point of the ordering is that JavaScript has no EPSG table, so a
 * declared code can only be resolved *positively*. 4326 is known geographic;
 * 4269 (NAD83, also geographic) and 3857 (not) are indistinguishable by number
 * alone, so both have to fall through to the coordinate-magnitude test rather
 * than be guessed at.
 */
import {
  detectCoordinateFormat,
  detectCrs,
  epsgFromCrsName,
  firstCoordinate,
} from "../../utils/geoCrs";

const urn = (code: number) => `urn:ogc:def:crs:EPSG::${code}`;

const polygon = (x: number, y: number) => ({
  type: "Polygon",
  coordinates: [[[x, y], [x, y + 1], [x + 1, y + 1], [x, y]]],
});

describe("epsgFromCrsName", () => {
  test("reads a single- and double-colon urn", () => {
    expect(epsgFromCrsName(urn(3395))).toBe(3395);
    expect(epsgFromCrsName("EPSG:4326")).toBe(4326);
  });

  test("is null for nothing useful", () => {
    expect(epsgFromCrsName(undefined)).toBeNull();
    expect(epsgFromCrsName("")).toBeNull();
    expect(epsgFromCrsName("not a crs")).toBeNull();
  });
});

describe("firstCoordinate", () => {
  test("finds the first pair at any nesting depth", () => {
    expect(firstCoordinate([1, 2])).toEqual([1, 2]);
    expect(firstCoordinate([[[3, 4], [5, 6]]])).toEqual([3, 4]);
  });

  test("recurses into a GeometryCollection", () => {
    // Bailing here silently yielded the wrong projection for the whole layer,
    // because a collection has no `coordinates` of its own.
    const collection = {
      type: "GeometryCollection",
      geometries: [polygon(7, 8), { type: "Point", coordinates: [9, 10] }],
    };

    expect(firstCoordinate(collection)).toEqual([7, 8]);
  });

  test("is null for empty or non-array input", () => {
    expect(firstCoordinate([])).toBeNull();
    expect(firstCoordinate(null)).toBeNull();
    expect(firstCoordinate({ type: "Point" })).toBeNull();
  });
});

describe("detectCrs", () => {
  test("4326 resolves positively as geographic", () => {
    expect(detectCrs(urn(4326), [polygon(-87, 41)])).toEqual({
      epsg: 4326,
      projected: false,
    });
  });

  test("metre-scale coordinates are projected", () => {
    expect(detectCrs(urn(3395), [polygon(-9755000, 5140000)]).projected).toBe(true);
  });

  test("4269 falls through to magnitude and reads as geographic", () => {
    // Geographic, but not a code we can resolve without a lookup table.
    const crs = detectCrs(urn(4269), [polygon(-87, 41)]);

    expect(crs.epsg).toBe(4269);
    expect(crs.projected).toBe(false);
  });

  test("no declared CRS still picks a projection from magnitude", () => {
    expect(detectCrs(undefined, [polygon(-87, 41)]).projected).toBe(false);
    expect(detectCrs(undefined, [polygon(-9755000, 5140000)]).projected).toBe(true);
  });

  test("no geometries at all is treated as lon/lat", () => {
    expect(detectCrs(undefined, []).projected).toBe(false);
  });

  test("a projected GeometryCollection is still detected", () => {
    const collection = {
      type: "GeometryCollection",
      geometries: [polygon(-9755000, 5140000)],
    };

    expect(detectCrs(undefined, [collection]).projected).toBe(true);
  });
});

describe("detectCoordinateFormat", () => {
  // autk-db's legacy contract. The strings are what `loadGeojson` expects, so
  // they must not drift while the module is shared with the Vega path.
  test("returns the declared EPSG code verbatim", () => {
    const fc = { crs: { properties: { name: urn(3395) } }, features: [] };

    expect(detectCoordinateFormat(fc)).toBe("EPSG:3395");
  });

  test("falls back to EPSG:3395 for projected coordinates", () => {
    const fc = { features: [{ geometry: polygon(-9755000, 5140000) }] };

    expect(detectCoordinateFormat(fc)).toBe("EPSG:3395");
  });

  test("falls back to EPSG:4326 otherwise", () => {
    const fc = { features: [{ geometry: polygon(-87, 41) }] };

    expect(detectCoordinateFormat(fc)).toBe("EPSG:4326");
    expect(detectCoordinateFormat({ features: [] })).toBe("EPSG:4326");
  });
});
