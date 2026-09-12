/**
 * The single path from an input payload to render-ready rows.
 *
 * The property that matters most here is the *gate*: geometry is attached
 * because the spec draws it, not because the payload happens to be a
 * GeoDataFrame. Shipped dataflows chart a 1.5 MB GeoJSON as a bar chart, and
 * attaching geometry unconditionally would inline all of it into
 * `spec.data.values` and re-ship it through `changeset()` on every brush.
 */
import { prepareVegaInput } from "../../utils/vegaInput";

jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
}));

const { fetchData } = require("../../services/api");

const polygon = { type: "Polygon", coordinates: [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]] };

const geoPayload = {
  type: "FeatureCollection",
  geometry_name: "geometry",
  features: [
    { properties: { zip: "60601", pop: 2746 }, geometry: polygon },
    { properties: { zip: "60602", pop: 8804 }, geometry: polygon },
  ],
};

const framePayload = { zip: { 0: "60601", 1: "60602" }, pop: { 0: 2746, 1: 8804 } };

beforeEach(() => {
  (fetchData as jest.Mock).mockReset();
});

describe("the payload gate", () => {
  test("a non-geo spec over a GeoDataFrame carries no geometry", () => {
    return prepareVegaInput(
      { dataType: "geodataframe", data: geoPayload },
      { mark: "bar", encoding: { x: { field: "zip" }, y: { field: "pop" } } },
    ).then(({ values }) => {
      expect(values[0].geometry).toBeUndefined();
      expect(values[0]).toEqual({ zip: "60601", pop: 2746, __row_index__: 0 });
    });
  });

  test("a geoshape spec over the same payload does carry it", async () => {
    const { values } = await prepareVegaInput(
      { dataType: "geodataframe", data: geoPayload },
      { mark: "geoshape" },
    );

    expect(values[0].geometry.type).toBe("Feature");
  });
});

describe("input types", () => {
  test("a rejected input type reports a reason rather than throwing", async () => {
    // This used to throw from an unawaited async call, so nothing caught it and
    // the toast it was meant to raise never appeared.
    const result = await prepareVegaInput({ dataType: "raster", data: {} }, { mark: "bar" });

    expect(result.emptyReason).toBe("input-type-rejected");
    expect(result.values).toEqual([]);
  });

  test("an empty input is simply no rows", async () => {
    expect((await prepareVegaInput("", { mark: "bar" })).values).toEqual([]);
    expect((await prepareVegaInput(null, { mark: "bar" })).values).toEqual([]);
  });
});

describe("fetching", () => {
  test("reads by path when the payload is a reference", async () => {
    (fetchData as jest.Mock).mockResolvedValue({ data: framePayload });

    const { values } = await prepareVegaInput(
      { dataType: "dataframe", path: "art-12" },
      { mark: "bar" },
    );

    expect(fetchData).toHaveBeenCalledWith("art-12");
    expect(values).toHaveLength(2);
  });

  test("uses inline data when there is no path", async () => {
    const { values } = await prepareVegaInput(
      { dataType: "dataframe", data: framePayload },
      { mark: "bar" },
    );

    expect(fetchData).not.toHaveBeenCalled();
    expect(values[0].zip).toBe("60601");
  });
});

describe("row index", () => {
  test("__row_index__ is positional and survives the geo passes", async () => {
    const { values } = await prepareVegaInput(
      { dataType: "geodataframe", data: geoPayload },
      { mark: "geoshape" },
    );

    expect(values.map((v: any) => v.__row_index__)).toEqual([0, 1]);
  });
});

describe("a plain DataFrame carrying geometry", () => {
  test("is still coerced when the spec asks for a geojson field", async () => {
    // `pd.DataFrame(gdf)` produces this: no declared geometry_name, geometry
    // values sitting in ordinary columns. Gating on the spec rather than the
    // dataType is what makes it work.
    const { values, emptyReason } = await prepareVegaInput(
      { dataType: "dataframe", data: { where: { 0: polygon } } },
      { mark: "geoshape" },
    );

    expect(emptyReason).toBeUndefined();
    expect(values[0].where.type).toBe("Feature");
  });
});

describe("unresolvable geometry", () => {
  test("a geoshape over data with no geometry reports it", async () => {
    const { emptyReason } = await prepareVegaInput(
      { dataType: "dataframe", data: framePayload },
      { mark: "geoshape" },
    );

    expect(emptyReason).toBe("geometry-unresolved");
  });
});
