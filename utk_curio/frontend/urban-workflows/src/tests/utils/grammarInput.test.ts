/**
 * The one path from a grammar node's input to the frames it draws, shared by
 * the Vega-Lite and Autark nodes.
 */
const mockFetchData = jest.fn();
const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: (...args: any[]) => mockFetchData(...args),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import { framesFromPayload, readGrammarInput } from "../../utils/grammarInput";

const VEGA = { label: "the 2D Plot (Vega-Lite)" };
const AUTK = { label: "the Autark node", bundles: true };

const fc = (n = 1) => ({
  type: "FeatureCollection",
  features: Array.from({ length: n }, (_, i) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [i, i] },
    properties: { value: i },
  })),
});

beforeEach(() => {
  mockFetchData.mockReset();
  mockFetchPreviewData.mockReset();
});

describe("readGrammarInput", () => {
  test("no input, no frames", async () => {
    expect(await readGrammarInput("", VEGA)).toEqual({ frames: [] });
    expect(await readGrammarInput(null, VEGA)).toEqual({ frames: [] });
  });

  test("a reference that names a refused type is refused before any fetch", async () => {
    const read = await readGrammarInput({ path: "art", dataType: "raster" }, VEGA);
    expect(read).toEqual({
      frames: [],
      emptyReason: "input-type-rejected",
      detail: "raster is not a valid input type for the 2D Plot (Vega-Lite).",
    });
    expect(mockFetchData).not.toHaveBeenCalled();
  });

  test("a reference is fetched; its schema and geometry come off the envelope", async () => {
    const payload = { ...fc(2), geometry_name: "geom", crs: { properties: { name: "urn:ogc:def:crs:EPSG::3395" } } };
    mockFetchData.mockResolvedValue({ dataType: "geodataframe", data: payload, schema: { value: "int64" } });

    const read = await readGrammarInput({ path: "art", dataType: "geodataframe" }, VEGA);

    expect(mockFetchData).toHaveBeenCalledWith("art");
    expect(read.frames).toHaveLength(1);
    expect(read.frames[0]).toMatchObject({
      name: null,
      dataType: "geodataframe",
      payload,
      schema: { value: "int64" },
      geometryName: "geom",
      crsName: "urn:ogc:def:crs:EPSG::3395",
      fromBundle: false,
    });
  });

  test("a geodataframe takes the Autark layer type its metadata names", async () => {
    // What the sandbox sends for `gdf.metadata = {"layerType": "buildings"}`, the
    // line a Discovery OpenStreetMap download's loader writes.
    const typed = (layerType: unknown) => ({ ...fc(1), metadata: { name: "x", layerType } });
    mockFetchData.mockResolvedValueOnce({ dataType: "geodataframe", data: typed("buildings") });
    const read = await readGrammarInput({ path: "art", dataType: "geodataframe" }, AUTK);
    expect(read.frames[0].layerType).toBe("buildings");

    // Not one of Autark's layer types: no type.
    mockFetchData.mockResolvedValueOnce({ dataType: "geodataframe", data: typed("towers") });
    expect((await readGrammarInput({ path: "art" }, AUTK)).frames[0].layerType).toBeUndefined();
    mockFetchData.mockResolvedValueOnce({ dataType: "geodataframe", data: typed(7) });
    expect((await readGrammarInput({ path: "art" }, AUTK)).frames[0].layerType).toBeUndefined();

    // A layer type the envelope carries still wins.
    mockFetchData.mockResolvedValueOnce({ dataType: "geodataframe", data: typed("buildings"), layerType: "roads" });
    expect((await readGrammarInput({ path: "art" }, AUTK)).frames[0].layerType).toBe("roads");
  });

  test("inline rows are read as they are", async () => {
    const input = { dataType: "dataframe", data: { a: [1, 2] }, schema: { a: "int64" } };
    const read = await readGrammarInput(input, VEGA);
    expect(mockFetchData).not.toHaveBeenCalled();
    expect(read.frames[0]).toMatchObject({ dataType: "dataframe", payload: { a: [1, 2] }, geometryName: null });
  });

  test("a starter reads the preview, not the whole artifact", async () => {
    mockFetchPreviewData.mockResolvedValue({ dataType: "dataframe", data: { a: [1] } });
    await readGrammarInput({ path: "art", dataType: "dataframe" }, { ...VEGA, preview: true });
    expect(mockFetchPreviewData).toHaveBeenCalledWith("art");
    expect(mockFetchData).not.toHaveBeenCalled();
  });

  test("a reference restored without its type is gated on what it holds", async () => {
    mockFetchData.mockResolvedValueOnce({ dataType: "dataframe", data: { a: [1] } });
    expect((await readGrammarInput({ path: "art" }, VEGA)).frames).toHaveLength(1);

    mockFetchData.mockResolvedValueOnce({ dataType: "raster", data: {} });
    expect((await readGrammarInput({ path: "art" }, VEGA)).detail)
      .toBe("raster is not a valid input type for the 2D Plot (Vega-Lite).");
  });

  test("without `circles` or `bundles` a bundle is refused; Autark reads it", async () => {
    const bundle = {
      dataType: "outputs",
      data: [
        { dataType: "geodataframe", data: fc(1), layerName: "roads", layerType: "roads" },
        { dataType: "geodataframe", data: fc(2) },
        { dataType: "dataframe", data: { a: [1] } },
        { dataType: "raster", data: {} },
      ],
    };
    expect((await readGrammarInput(bundle, VEGA)).emptyReason).toBe("input-type-rejected");

    const read = await readGrammarInput(bundle, AUTK);
    expect(read.frames.map((f) => [f.name, f.dataType, f.index, f.fromBundle, f.circle])).toEqual([
      ["roads", "geodataframe", 0, true, 0],
      [null, "geodataframe", 1, true, 1],
      [null, "dataframe", 2, true, 2],
    ]);
    expect(read.frames[0].layerType).toBe("roads");
    expect(read.skipped).toEqual(["raster at position 3"]);
  });

  test("with `circles` (Vega-Lite), several inputs are a frame each; any other bundle is still refused", async () => {
    const inputs = {
      dataType: "outputs",
      data: [
        { dataType: "dataframe", data: { a: [1] } },
        { dataType: "geodataframe", data: fc(2) },
      ],
    };
    const read = await readGrammarInput(inputs, { ...VEGA, circles: true });
    expect(read.frames.map((f) => [f.dataType, f.circle])).toEqual([["dataframe", 0], ["geodataframe", 1]]);

    const tabs = { dataType: "list", data: [{ dataType: "dataframe", data: { a: [1] } }] };
    expect((await readGrammarInput(tabs, { ...VEGA, circles: true })).detail)
      .toBe("list is not a valid input type for the 2D Plot (Vega-Lite).");
  });

  test("an input that holds an Autark node's tables brings each of them, under that input's position", async () => {
    mockFetchData.mockImplementation(async (path: string) => (path === "art-b"
      ? {
          dataType: "list",
          data: [
            { dataType: "dict", data: { name: "table_osm_roads", type: "roads", geojson: fc(1) } },
            { dataType: "dict", data: { name: "table_osm_buildings", type: "buildings", geojson: fc(2) } },
          ],
        }
      : { dataType: "geodataframe", data: fc(3) }));
    const inputs = {
      dataType: "outputs",
      data: [{ path: "art-a", dataType: "geodataframe" }, { path: "art-b", dataType: "list" }],
    };
    const read = await readGrammarInput(inputs, AUTK);
    expect(read.frames.map((f) => [f.name, f.circle])).toEqual([
      [null, 0],
      ["table_osm_roads", 1],
      ["table_osm_buildings", 1],
    ]);
    expect(read.frames[1].layerType).toBe("roads");
    expect(read.skipped).toBeUndefined();
    mockFetchData.mockReset();
  });

  test("an Autark data node's table list keeps each table's name and layer type", async () => {
    mockFetchData.mockResolvedValue({
      dataType: "list",
      data: [
        { dataType: "dict", data: { name: "table_osm_roads", type: "roads", geojson: fc(1) } },
        { dataType: "dict", data: { name: "table_osm_water", type: "water", geojson: fc(1) } },
      ],
    });
    const read = await readGrammarInput({ path: "art", dataType: "list" }, AUTK);
    expect(read.frames.map((f) => [f.name, f.layerType])).toEqual([
      ["table_osm_roads", "roads"],
      ["table_osm_water", "water"],
    ]);
  });

  test("a compute node's pool wrapper is peeled to its layers", async () => {
    mockFetchData.mockResolvedValue({
      dataType: "dict",
      data: { dataType: "outputs", data: [{ dataType: "geodataframe", data: fc(3), layerName: "lots" }] },
    });
    const read = await readGrammarInput({ path: "art", dataType: "dict" }, AUTK);
    expect(read.frames.map((f) => f.name)).toEqual(["lots"]);
  });

  test("a Merge bundle's references are fetched one by one", async () => {
    mockFetchData.mockImplementation(async (path: string) =>
      path === "a" ? { dataType: "geodataframe", data: fc(1) } : { dataType: "raster", data: {} },
    );
    const merge = {
      dataType: "outputs",
      data: [
        { path: "a", dataType: "geodataframe" },
        { path: "b", dataType: "raster" },
      ],
    };
    const read = await readGrammarInput(merge, AUTK);
    expect(mockFetchData.mock.calls.map((c) => c[0])).toEqual(["a", "b"]);
    expect(read.frames.map((f) => [f.index, f.dataType])).toEqual([[0, "geodataframe"]]);
    expect(read.skipped).toEqual(["raster at position 1"]);
  });

  test("a bundle holding nothing drawable says so", async () => {
    const read = await readGrammarInput(
      { dataType: "outputs", data: [{ dataType: "raster", data: {} }] },
      AUTK,
    );
    expect(read).toMatchObject({
      frames: [],
      emptyReason: "input-type-rejected",
      detail: "This outputs holds nothing the Autark node can draw.",
      skipped: ["raster at position 0"],
    });
  });
});

describe("framesFromPayload", () => {
  test("a bare FeatureCollection is one layer", () => {
    const { frames } = framesFromPayload(fc(2));
    expect(frames).toHaveLength(1);
    expect(frames[0]).toMatchObject({ dataType: "geodataframe", name: null, fromBundle: false });
  });

  test("nothing in, nothing out", () => {
    expect(framesFromPayload(null)).toEqual({ frames: [], refs: [], skipped: [] });
  });
});
