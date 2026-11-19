/**
 * A raster an input carries is read as its tables are (#662's chips): the one
 * `/get-preview` read the header makes, through the grammar nodes' reader,
 * with rasters among the frames it gives. So a raster is one of the input's
 * layers, by the name an Autark node gives its table or the key a Python
 * node's dict gives it, and a chip that names it is accepted wherever a chip
 * naming a table of that name is. A raster has no columns, and what the
 * preview keeps of it is its size, its bands and its CRS.
 *
 * Found 11-18 building example 34: a chip naming its heatmap,
 * `[!! input_0:park_access !!]`, was refused as a layer the input does not
 * have, since the read left every raster out.
 */
const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import { readAutkInput } from "../../utils/autkInput";
import { resolveReferences, type ReferenceScope } from "../../utils/references/codeReferences";
import { inputScopeFor, readInputColumns, readInputPreview } from "../../utils/references/inputScope";
import {
  BROWSER_LAYERS_REF,
  PARK_ACCESS,
  PYTHON_DICT_REF,
  PYTHON_RASTER_REF,
  RASTER_READS,
  SERVER_LAYERS_REF,
} from "../_support/rasterInputFixtures";

beforeEach(() => {
  mockFetchPreviewData.mockReset();
  mockFetchPreviewData.mockImplementation(async (path: string) => {
    if (!(path in RASTER_READS)) throw new Error(`no artifact ${path}`);
    return RASTER_READS[path];
  });
});

/** The heatmap, as a preview keeps it. */
const PARK_ACCESS_SEEN = { width: 3, height: 2, bands: ["count_tip_parks"], crs: "EPSG:3395" };
/** The Python node's elevation raster, as a preview keeps it: a band with no
 * description is named as autk-db names it when an Autark node loads it. */
const ELEVATION_SEEN = { width: 40, height: 30, bands: ["elevation_m", "band_2"], crs: "EPSG:3395" };

/** The scope of the node that *value* feeds on its circle 0, read as the editor reads it. */
async function scopeOf(value: unknown): Promise<ReferenceScope> {
  const columns = await readInputColumns(value);
  const edges = [{ id: "e0", source: "data", target: "next", sourceHandle: "out", targetHandle: "in" }];
  const nodes = [{ id: "data", data: { title: "Park access" } }];
  const inputs = inputScopeFor("next", edges, nodes, () => value, (data) => data.title ?? null, () => columns);
  return { widgets: [], inputs };
}

/** Example 34's map, with a chip for the parks and one for the heatmap. */
const MAP_SPEC =
  '{"map": {"layerRefs": [{"dataRef": [!! input_0:tip_parks !!]}, {"dataRef": [!! input_0:park_access !!], "getFnv": "count.tip_parks"}]}}';

describe("an Autark node's heatmap is one of the layers it hands on", () => {
  for (const [how, ref] of [
    ["a run on the server", SERVER_LAYERS_REF],
    ["a run in the browser", BROWSER_LAYERS_REF],
  ] as const) {
    test(`as ${how} hands it on: listed after its tables, with no columns`, async () => {
      expect(await readInputColumns(ref)).toEqual({
        columns: [],
        dtypes: {},
        layers: [
          { name: "tip_parks", columns: ["osm_id", "leisure"], dtypes: {} },
          { name: "tip_roads", columns: ["osm_id", "highway"], dtypes: {} },
          { name: "park_access", columns: [], dtypes: {}, raster: true },
        ],
      });
      // One read, the one the header makes.
      expect(mockFetchPreviewData).toHaveBeenCalledTimes(1);
      expect(mockFetchPreviewData).toHaveBeenCalledWith(ref.path);
    });

    test(`as ${how} hands it on: a chip naming it is accepted in a spec and in code, as a table's is`, async () => {
      const scope = await scopeOf(ref);
      expect(resolveReferences(MAP_SPEC, scope, "json")).toEqual({
        code: '{"map": {"layerRefs": [{"dataRef": "tip_parks"}, {"dataRef": "park_access", "getFnv": "count.tip_parks"}]}}',
        problems: [],
      });
      expect(resolveReferences("heat = [!! input_0:park_access !!]", scope, "python")).toEqual({
        code: 'heat = curio_layer(input_0, "park_access", 0)',
        problems: [],
      });
      expect(resolveReferences("const heat = [!! input_0:park_access !!];", scope, "javascript")).toEqual({
        code: 'const heat = curio_layer(input_0, "park_access", 0);',
        problems: [],
      });
    });

    test(`as ${how} hands it on: its preview keeps its size, its bands and its CRS`, async () => {
      const preview: any = await readInputPreview(ref);
      expect(preview.kind).toBe("layers");
      expect(preview.layers.map((layer: any) => layer.name)).toEqual(["tip_parks", "tip_roads", "park_access"]);
      expect(preview.layers[2]).toEqual({ name: "park_access", raster: PARK_ACCESS_SEEN });
      // Its tables are read as before.
      expect(preview.layers[0].table).toMatchObject({ columns: ["osm_id", "leisure"], totalRows: 1, geometryType: "Point" });
    });
  }

  test("a chip naming a layer it does not have is still refused, naming the raster among its layers", async () => {
    const scope = await scopeOf(SERVER_LAYERS_REF);
    expect(resolveReferences("water = [!! input_0:tip_water !!]", scope, "python").problems).toEqual([
      {
        reference: "[!! input_0:tip_water !!]",
        message: "[!! input_0:tip_water !!]: input_0 has no layer tip_water. Its layers are tip_parks, tip_roads, park_access.",
      },
    ]);
  });
});

describe("a Python node's dict of frames: a raster in it is a layer named after its key", () => {
  test("listed among the dict's frames, in the dict's order, with no columns", async () => {
    expect(await readInputColumns(PYTHON_DICT_REF)).toEqual({
      columns: [],
      dtypes: {},
      layers: [
        {
          name: "tip_parks",
          columns: ["osm_id", "leisure", "geometry"],
          dtypes: { osm_id: "int64", leisure: "str", geometry: "geometry" },
        },
        {
          name: "tip_roads",
          columns: ["osm_id", "highway", "geometry"],
          dtypes: { osm_id: "int64", highway: "str", geometry: "geometry" },
        },
        { name: "elevation", columns: [], dtypes: {}, raster: true },
      ],
    });
  });

  test("a chip naming its key is accepted, in code and in a spec", async () => {
    const scope = await scopeOf(PYTHON_DICT_REF);
    expect(resolveReferences("dem = [!! input_0:elevation !!]", scope, "python")).toEqual({
      code: 'dem = curio_layer(input_0, "elevation", 0)',
      problems: [],
    });
    expect(resolveReferences('{"dataRef": [!! input_0:elevation !!]}', scope, "json")).toEqual({
      code: '{"dataRef": "elevation"}',
      problems: [],
    });
  });

  test("its preview keeps what the sandbox read of it: its size, its bands and its CRS", async () => {
    const preview: any = await readInputPreview(PYTHON_DICT_REF);
    expect(preview.kind).toBe("layers");
    expect(preview.layers[2]).toEqual({ name: "elevation", raster: ELEVATION_SEEN });
  });

  test("a dict of one table and one raster holds two layers, not the table's columns", async () => {
    const pair = { path: "python-pair", dataType: "dict" };
    expect(await readInputColumns(pair)).toEqual({
      columns: [],
      dtypes: {},
      layers: [
        {
          name: "tip_parks",
          columns: ["osm_id", "leisure", "geometry"],
          dtypes: { osm_id: "int64", leisure: "str", geometry: "geometry" },
        },
        { name: "elevation", columns: [], dtypes: {}, raster: true },
      ],
    });
  });
});

describe("a Python node's dict that holds rasters alone, read as one holding a table is", () => {
  const ref = { path: "python-rasters", dataType: "dict" };

  test("each raster is a layer named after its key, which a chip names", async () => {
    expect(await readInputColumns(ref)).toEqual({
      columns: [],
      dtypes: {},
      layers: [
        { name: "day", columns: [], dtypes: {}, raster: true },
        { name: "night", columns: [], dtypes: {}, raster: true },
      ],
    });
    const scope = await scopeOf(ref);
    expect(resolveReferences("night = [!! input_0:night !!]", scope, "python")).toEqual({
      code: 'night = curio_layer(input_0, "night", 0)',
      problems: [],
    });
    const preview: any = await readInputPreview(ref);
    expect(preview.layers).toEqual([
      { name: "day", raster: ELEVATION_SEEN },
      { name: "night", raster: ELEVATION_SEEN },
    ]);
  });

  test("an Autark node reads each by its place in the dict, under its key", async () => {
    const read = await readAutkInput(ref, { preview: true });
    expect(read.frames.map((frame) => [frame.name, frame.dataType, frame.payload])).toEqual([
      ["day", "raster", { artifact: "python-rasters", part: 0 }],
      ["night", "raster", { artifact: "python-rasters", part: 1 }],
    ]);
  });
});

describe("a raster in a tuple, and a raster on its own", () => {
  test("a tuple's raster is one of its values, kept as a raster, not as the text of its file", async () => {
    const preview: any = await readInputPreview({ path: "python-tuple", dataType: "outputs" });
    expect(preview.kind).toBe("tuple");
    expect(preview.size).toBe(2);
    expect(preview.parts[0].table).toMatchObject({ columns: ["osm_id", "leisure"], totalRows: 1 });
    expect(preview.parts[1]).toEqual({ raster: ELEVATION_SEEN });
  });

  test("an Autark node's raster handed on inline is read for what it is, with no read", async () => {
    expect(await readInputPreview(PARK_ACCESS)).toEqual({ kind: "raster", raster: PARK_ACCESS_SEEN });
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });

  test("the header reads nothing for a raster on its own: it has no columns", async () => {
    expect(await readInputColumns(PYTHON_RASTER_REF)).toEqual({ columns: [], dtypes: {} });
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });
});
