/**
 * A raster on the Autark node's input (#662, step 8), read through the path
 * the Autark and Vega-Lite nodes share (utils/grammarInput). The Autark node
 * takes it as the table `input_<k>`, like any other input, and is told where
 * the raster is rather than handed its bytes; the Vega-Lite node still refuses
 * it in the same sentence as before.
 */
const mockFetchData = jest.fn();
const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: (...args: any[]) => mockFetchData(...args),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import { autkSourcesFrom, readAutkInput } from "../../utils/autkInput";
import { readGrammarInput } from "../../utils/grammarInput";
import { autkStarterText } from "../../utils/autkDefaultSpec";
import cases from "../../utils/raster/rasterWire.cases.json";

const MAP_ON = (...refs: string[]) => ({ map: { layerRefs: refs.map((dataRef) => ({ dataRef, getFnv: "band_1" })) } });
const ENVELOPE = cases.cases[0].envelope;

const fc = () => ({
  type: "FeatureCollection",
  features: [{ type: "Feature", geometry: { type: "Point", coordinates: [0, 0] }, properties: { value: 1 } }],
});

beforeEach(() => {
  mockFetchData.mockReset();
  mockFetchPreviewData.mockReset();
});

describe("a Python node's raster", () => {
  test("is the table input_0, named by its artifact and never fetched as rows", async () => {
    const read = await readAutkInput({ path: "art-heat", dataType: "raster" });
    expect(mockFetchData).not.toHaveBeenCalled();
    expect(read.frames).toHaveLength(1);
    expect(read.frames[0]).toMatchObject({ dataType: "raster", payload: { artifact: "art-heat" }, circle: 0 });

    const prepared = autkSourcesFrom(read, MAP_ON("input_0"));
    expect(prepared.sources).toEqual([]);
    expect(prepared.rasters).toEqual([{ outputTableName: "input_0", payload: { artifact: "art-heat" } }]);
    expect(prepared.tables).toEqual(["input_0"]);
    expect(prepared.emptyReason).toBeUndefined();
    expect(prepared.inputProblem).toBeUndefined();
  });

  test("is still refused by the Vega-Lite node, in the same sentence as before", async () => {
    const read = await readGrammarInput({ path: "art-heat", dataType: "raster" }, { label: "the 2D Plot (Vega-Lite)", circles: true });
    expect(read).toEqual({
      frames: [],
      emptyReason: "input-type-rejected",
      detail: "raster is not a valid input type for the 2D Plot (Vega-Lite).",
    });
  });

  test("restored without its type, it is found to be a raster and named by its artifact", async () => {
    mockFetchData.mockResolvedValue({ dataType: "raster", data: "/app/data/heat.tif" });
    const read = await readAutkInput({ path: "art-heat" });
    expect(read.frames.map((f) => [f.dataType, f.payload])).toEqual([["raster", { artifact: "art-heat" }]]);
  });

  test("beside a layer, each input is its own table, in circle order", async () => {
    mockFetchData.mockResolvedValue({ dataType: "geodataframe", data: fc() });
    const read = await readAutkInput({
      dataType: "outputs",
      data: [{ path: "art-roads", dataType: "geodataframe" }, { path: "art-heat", dataType: "raster" }],
    });
    expect(mockFetchData.mock.calls.map((c) => c[0])).toEqual(["art-roads"]);
    const prepared = autkSourcesFrom(read, MAP_ON("input_0", "input_1"));
    expect(prepared.sources.map((s) => s.outputTableName)).toEqual(["input_0"]);
    expect(prepared.rasters).toEqual([{ outputTableName: "input_1", payload: { artifact: "art-heat" } }]);
    expect(prepared.tables).toEqual(["input_0", "input_1"]);
  });

  test("a raster in a Python tuple is named by its place in it", async () => {
    mockFetchData.mockResolvedValue({
      dataType: "outputs",
      data: [{ dataType: "geodataframe", data: fc() }, { dataType: "raster", data: "/app/data/heat.tif" }],
    });
    const read = await readAutkInput({ path: "art-tuple", dataType: "outputs" });
    expect(read.frames.map((f) => [f.dataType, f.payload.artifact ?? null, f.payload.part ?? null])).toEqual([
      ["geodataframe", null, null],
      ["raster", "art-tuple", 1],
    ]);
  });
});

describe("a raster an upstream Autark node handed on", () => {
  test("arrives as its collection, under the layer name it was given", async () => {
    mockFetchData.mockResolvedValue({ dataType: "dict", data: { ...ENVELOPE, layerName: "heat" } });
    const read = await readAutkInput({ path: "art-autk", dataType: "dict" });
    expect(read.frames).toHaveLength(1);
    expect(read.frames[0]).toMatchObject({ name: "heat", dataType: "raster", payload: { envelope: { dataType: "raster" } } });

    // A one-layer input is `input_0` too, when the document reads that name.
    const prepared = autkSourcesFrom(read, MAP_ON("input_0"));
    expect(prepared.rasters.map((r) => r.outputTableName)).toEqual(["input_0", "heat"]);
  });

  test("beside the layers of a compute step's output", async () => {
    mockFetchData.mockResolvedValue({
      dataType: "dict",
      data: {
        dataType: "outputs",
        data: [
          { dataType: "geodataframe", data: fc(), layerName: "roads", layerType: "roads" },
          { ...ENVELOPE, layerName: "heat" },
        ],
      },
    });
    const read = await readAutkInput({ path: "art-autk", dataType: "dict" });
    expect(read.frames.map((f) => [f.name, f.dataType])).toEqual([["roads", "geodataframe"], ["heat", "raster"]]);
    expect(read.skipped).toBeUndefined();
  });
});

test("a raster offers no starter document: the editor stays empty for one", async () => {
  const read = await readAutkInput({ path: "art-heat", dataType: "raster" });
  expect(autkStarterText(read)).toBeNull();
});
