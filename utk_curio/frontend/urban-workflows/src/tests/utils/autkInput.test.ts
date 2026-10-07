/**
 * The Autark node's input, read the way the Vega-Lite node reads its own, as
 * the tables an Autark document names.
 */
const mockFetchData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: (...args: any[]) => mockFetchData(...args),
  fetchPreviewData: jest.fn(),
}));

import {
  autkNeedsInput,
  autkSourcesFrom,
  documentTableRefs,
  loadableSource,
  ownTableNames,
  inputRow,
  prepareAutkInput,
  tablePositions,
  type PreparedAutkInput,
} from "../../utils/autkInput";
import type { GrammarFrame, GrammarInput } from "../../utils/grammarInput";
import { resolveReferences } from "../../utils/references/codeReferences";
import { inputScopeFor } from "../../utils/references/inputScope";

const point = (x: number, y: number) => ({ type: "Point", coordinates: [x, y] });
const fc = (geoms: any[], crs?: string) => ({
  type: "FeatureCollection",
  ...(crs ? { crs: { properties: { name: crs } } } : {}),
  features: geoms.map((geometry, i) => ({ type: "Feature", geometry, properties: { value: i } })),
});

function frame(over: Partial<GrammarFrame>): GrammarFrame {
  return {
    name: null,
    dataType: "geodataframe",
    payload: fc([point(1, 1)]),
    schema: null,
    geometryName: "geometry",
    crsName: null,
    fromBundle: false,
    index: 0,
    circle: 0,
    ...over,
  };
}
const read = (...frames: GrammarFrame[]): GrammarInput => ({ frames });
const MAP_ON = (...refs: string[]) => ({ map: { layerRefs: refs.map((dataRef) => ({ dataRef })) } });

describe("documentTableRefs", () => {
  test("maps, plots and compute blocks, as objects or arrays", () => {
    const spec = {
      map: [{ layerRefs: [{ dataRef: "a" }] }, { layerRefs: [{ dataRef: "b" }] }],
      plot: { dataRef: "c", mapRef: "a" },
      compute: [{
        dataRef: "d",
        uniforms: { k: { fromFeature: { layer: "e", path: "x" } }, n: 1 },
        uniformMatrices: { m: { fromFeature: { layer: "f", path: "y" } } },
      }],
    };
    expect(documentTableRefs(spec).sort()).toEqual(["a", "b", "c", "d", "e", "f"]);
  });
});

describe("autkNeedsInput", () => {
  const osm = { type: "osm", outputTableName: "t", autoLoadLayers: { layers: ["roads"] }, queryArea: {} };

  test("a document drawing what its own data section loads needs nothing", () => {
    expect(autkNeedsInput({ data: [osm], ...MAP_ON("t_roads") })).toBe(false);
    expect(autkNeedsInput({ data: [osm] })).toBe(false);
  });

  test("a document naming a table it does not create reads its input", () => {
    expect(autkNeedsInput(MAP_ON("input_0"))).toBe(true);
    expect(autkNeedsInput({ data: [osm], ...MAP_ON("t_roads", "table_osm_water") })).toBe(true);
  });

  test("a compute-only document works on what arrives", () => {
    expect(autkNeedsInput({ compute: [{ dataRef: "x", wglsFunction: "" }] })).toBe(true);
  });

  test("a heatmap's table is the document's own", () => {
    const heat = { type: "heatmap", outputTableName: "h", tableJoinName: "t_roads", near: {}, grid: {} };
    expect(ownTableNames({ data: [osm, heat] }).sort()).toEqual(["h", "t_roads"]);
    expect(autkNeedsInput({ data: [osm, heat], ...MAP_ON("h") })).toBe(false);
  });
});

describe("autkSourcesFrom", () => {
  test("an empty layer an Autark data node stored comes back with no feature list: a table with no rows", () => {
    // What /get hands back for a layer the load found empty, e.g. a PBF area
    // with no water. The render drops it as it drops any empty table.
    const empty = { type: "FeatureCollection", features: null };
    const prepared = autkSourcesFrom(
      read(
        frame({ name: "table_osm_roads", fromBundle: true, index: 0, payload: fc([point(1, 1), point(2, 2)]) }),
        frame({ name: "table_osm_water", fromBundle: true, index: 1, payload: empty }),
      ),
      MAP_ON("table_osm_roads", "table_osm_water"),
    );
    expect(prepared.tables).toEqual(["table_osm_roads", "table_osm_water"]);
    expect(prepared.rowsIn).toBe(2);
    expect(prepared.inputProblem).toBeUndefined();
    expect(loadableSource(prepared.sources[1]).order).toEqual({ load: null, map: null });
  });

  test("a single frame is the table `input_0`, in the CRS it declares", () => {
    const prepared = autkSourcesFrom(
      read(frame({ payload: fc([point(1, 1)], "urn:ogc:def:crs:EPSG::32632") })),
      MAP_ON("input_0"),
    );
    expect(prepared.sources.map((s) => [s.outputTableName, s.coordinateFormat])).toEqual([
      ["input_0", "EPSG:32632"],
    ]);
    expect(prepared.rowsIn).toBe(1);
  });

  test("a named frame keeps its name; `input_0` is added only when the document reads it", () => {
    const named = read(frame({ name: "census" }));
    expect(autkSourcesFrom(named, MAP_ON("census")).sources.map((s) => s.outputTableName))
      .toEqual(["census"]);
    expect(autkSourcesFrom(named, MAP_ON("input_0")).sources.map((s) => s.outputTableName))
      .toEqual(["input_0", "census"]);
    expect(autkSourcesFrom(named, MAP_ON("input_0"), { alias: false }).sources.map((s) => s.outputTableName))
      .toEqual(["census"]);
  });

  test("several layers keep their own names: `input_0` names none of them (#483)", () => {
    // USAGE: "Several layers keep their own names". The alias used to point
    // `upstream` (now `input_0`) at layer 0 as well, which no doc said.
    const layers = read(
      frame({ name: "parks", fromBundle: true, index: 0 }),
      frame({ fromBundle: true, index: 1 }),
    );
    expect(autkSourcesFrom(layers, MAP_ON("input_0")).tables).toEqual(["parks", "input_1"]);
  });

  test("a bundle's unnamed layers are named by position, and keep their layer type", () => {
    const prepared = autkSourcesFrom(
      read(
        frame({ name: "table_osm_roads", layerType: "roads", fromBundle: true, index: 0 }),
        frame({ fromBundle: true, index: 1 }),
      ),
      MAP_ON("table_osm_roads"),
    );
    expect(prepared.sources.map((s) => [s.outputTableName, s.layerType])).toEqual([
      ["table_osm_roads", "roads"],
      ["input_1", undefined],
    ]);
  });

  describe("several input circles (#662)", () => {
    // What readGrammarInput hands over for a node with several inputs: each
    // frame carries the circle it came through.
    const on = (circle: number, over: Partial<GrammarFrame> = {}) =>
      frame({ fromBundle: true, index: circle, circle, ...over });

    test("each input is the table `input_<k>`; one holding a single named layer is also `input_<k>` when read so", () => {
      const inputs = read(on(0, { name: "census" }), on(1));
      expect(autkSourcesFrom(inputs, MAP_ON("input_0", "input_1")).tables)
        .toEqual(["input_0", "census", "input_1"]);
      expect(autkSourcesFrom(inputs, MAP_ON("census", "input_1")).tables).toEqual(["census", "input_1"]);
    });

    test("an input carrying several layers keeps their names, and `input_<k>` names none of them", () => {
      const inputs = read(
        on(0),
        on(1, { name: "table_osm_roads", layerType: "roads" }),
        on(1, { name: "table_osm_buildings", layerType: "buildings" }),
      );
      const prepared = autkSourcesFrom(inputs, MAP_ON("input_1", "table_osm_roads"));
      expect(prepared.tables).toEqual(["input_0", "table_osm_roads", "table_osm_buildings"]);
      expect(prepared.inputProblem).toBeUndefined();
    });

    test("a layer name two inputs bring is drawn from the first, and the problem names both", () => {
      const prepared = autkSourcesFrom(
        read(on(0, { name: "roads" }), on(1, { name: "roads", payload: fc([point(2, 2), point(3, 3)]) })),
        MAP_ON("roads"),
      );
      expect(prepared.tables).toEqual(["roads"]);
      expect(prepared.rowsIn).toBe(1);
      expect(prepared.inputProblem).toBe(
        "Inputs 0 and 1 both bring a layer named roads: roads means the one from input 0, "
        + "and input_1 means the one from input 1.",
      );
    });

    test("the second layer of a taken name is left out when it is not its input's `input_<k>`, and the problem says so", () => {
      // An input of several layers has no `input_<k>` for one of them, and a
      // compute step passes layers on under their own names only.
      const left = "Inputs 0 and 1 both bring a layer named roads: roads means the one from input 0, "
        + "and the one from input 1 is left out. Rename one of them.";
      const several = autkSourcesFrom(
        read(on(0, { name: "roads" }), on(1, { name: "roads" }), on(1, { name: "parks" })),
        MAP_ON("roads", "parks", "input_1"),
      );
      expect(several.tables).toEqual(["roads", "parks"]);
      expect(several.inputProblem).toBe(left);
      const computed = autkSourcesFrom(read(on(0, { name: "roads" }), on(1, { name: "roads" })), MAP_ON("input_1"), { alias: false });
      expect(computed.tables).toEqual(["roads"]);
      expect(computed.inputProblem).toBe(left);
    });

    test("several unnamed layers on one input are told apart by count", () => {
      expect(autkSourcesFrom(read(on(0), on(1), on(1)), MAP_ON("input_1")).tables)
        .toEqual(["input_0", "input_1", "input_1_1"]);
    });

    test("two inputs that bring a layer of one name are each still `input_<k>`, with their own rows (#744)", () => {
      // Two scenarios' copies of one node, each handing on its layer `routes`.
      const rain = fc([point(1, 1)]);
      const wind = fc([point(2, 2), point(3, 3)]);
      const prepared = autkSourcesFrom(
        read(on(0), on(1, { name: "routes", payload: rain }), on(2, { name: "routes", payload: wind })),
        MAP_ON("input_0", "input_1", "input_2"),
      );
      const drawn = (name: string) => prepared.sources.find((s) => s.outputTableName === name)?.geojsonObject;
      expect(drawn("input_1")).toBe(rain);
      expect(drawn("input_2")).toBe(wind);
      // The name itself is still the first input's layer, and the problem says so.
      expect(drawn("routes")).toBe(rain);
      expect([...prepared.tables].sort()).toEqual(["input_0", "input_1", "input_2", "routes"]);
      expect(prepared.rowsIn).toBe(4);
      expect(prepared.inputProblem).toBe(
        "Inputs 1 and 2 both bring a layer named routes: routes means the one from input 1, "
        + "and input_2 means the one from input 2.",
      );
    });

    test("a layer of a taken name that cannot be drawn leaves the other input's own layer drawn (#744)", () => {
      const roads = fc([point(2, 2)]);
      const prepared = autkSourcesFrom(
        read(
          on(0, { name: "roads", dataType: "dataframe", geometryName: null, payload: { lanes: [2] } }),
          on(1, { name: "roads", payload: roads }),
        ),
        MAP_ON("input_0", "input_1"),
      );
      expect(prepared.sources.map((s) => [s.outputTableName, s.geojsonObject])).toEqual([["input_1", roads]]);
      expect(prepared.unusable).toEqual(["roads", "input_0"]);
      expect(prepared.emptyReason).toBeUndefined();
    });
  });

  test("a buildings table gets heights autk-map can read, one feature per row", () => {
    // A GeoDataFrame gives every row every column: a building tagged only with
    // building:levels arrives with height null, and autk-map would cull it.
    const rows = [
      { height: 30, "building:levels": null },
      { height: null, "building:levels": 8 },
      { height: null, "building:levels": null },
    ];
    const payload = {
      type: "FeatureCollection",
      features: rows.map((properties) => ({ type: "Feature", geometry: point(1, 1), properties })),
    };
    const prepared = autkSourcesFrom(read(frame({ layerType: "buildings", payload })), MAP_ON("input_0"));
    expect(prepared.sources.map((s) => [s.outputTableName, s.layerType])).toEqual([["input_0", "buildings"]]);
    const features = prepared.sources[0].geojsonObject.features as any[];
    expect(features.map((f) => f.properties.height)).toEqual([30, 8 * 3.4, 6]);
    // The first already reads right, so it is the same feature; the input is not changed.
    expect(features[0]).toBe(payload.features[0]);
    expect(payload.features.map((f) => f.properties.height)).toEqual([30, null, null]);
  });

  test("any other table is passed on as it came", () => {
    const payload = {
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: point(1, 1), properties: { height: null, "building:levels": 8 } }],
    };
    for (const layerType of [undefined, "polygons"]) {
      const prepared = autkSourcesFrom(read(frame({ layerType, payload })), MAP_ON("input_0"));
      expect(prepared.sources[0].geojsonObject).toBe(payload);
    }
  });

  test("a DataFrame with one geometry column becomes a FeatureCollection, every row in place", () => {
    const prepared = autkSourcesFrom(
      read(frame({
        dataType: "dataframe",
        geometryName: null,
        payload: { zone: ["n", "s", "e"], where: [point(0, 0), null, point(2, 2)] },
      })),
      MAP_ON("input_0"),
    );
    const features = prepared.sources[0].geojsonObject.features as any[];
    expect(features.map((f) => f.geometry)).toEqual([point(0, 0), null, point(2, 2)]);
    expect(features.map((f) => f.properties)).toEqual([{ zone: "n" }, { zone: "s" }, { zone: "e" }]);
    expect(prepared.inputProblem).toBeUndefined();
  });

  test("a DataFrame with no geometry column is refused the way Vega refuses a geoshape", () => {
    const prepared = autkSourcesFrom(
      read(frame({ dataType: "dataframe", geometryName: null, payload: { zone: ["n"], pop: [3] } })),
      MAP_ON("input_0"),
    );
    expect(prepared).toMatchObject({
      sources: [],
      unusable: ["input_0"],
      emptyReason: "geometry-unresolved",
      detail: "input_0 has no geometry column, so there is nothing to draw. Return a GeoDataFrame.",
    });
    expect(prepared.inputProblem).toBe(prepared.detail);
  });

  test("a DataFrame with several geometry columns names them", () => {
    const prepared = autkSourcesFrom(
      read(frame({
        dataType: "dataframe",
        geometryName: null,
        payload: { a: [point(0, 0)], b: [point(1, 1)] },
      })),
      MAP_ON("input_0"),
    );
    expect(prepared.emptyReason).toBe("geometry-ambiguous");
    expect(prepared.detail).toContain("(a, b)");
  });

  test("a frame with no geometry in any row cannot be drawn", () => {
    const prepared = autkSourcesFrom(read(frame({ payload: fc([null, null]) })), MAP_ON("input_0"));
    expect(prepared.unusable).toEqual(["input_0"]);
    expect(prepared.detail).toBe("No row of input_0 has a geometry, so there is nothing to draw.");
  });

  test("what draws is drawn; what does not is named", () => {
    const prepared = autkSourcesFrom(
      {
        frames: [
          frame({ name: "roads", fromBundle: true, index: 0 }),
          frame({ name: "stats", dataType: "dataframe", geometryName: null, payload: { n: [1] }, fromBundle: true, index: 1 }),
        ],
        skipped: ["raster at position 2"],
      },
      MAP_ON("roads", "stats"),
    );
    expect(prepared.sources.map((s) => s.outputTableName)).toEqual(["roads"]);
    expect(prepared.unusable).toEqual(["stats"]);
    expect(prepared.emptyReason).toBeUndefined();
    expect(prepared.inputProblem).toBe(
      "stats has no geometry column, so there is nothing to draw. Return a GeoDataFrame. "
      + "Left out: raster at position 2.",
    );
  });

  test("a refused input is the table `input_0`, unusable, with the refusal as its reason", () => {
    const prepared = autkSourcesFrom(
      { frames: [], emptyReason: "input-type-rejected", detail: "raster is not a valid input type for the Autark node." },
      MAP_ON("input_0"),
    );
    expect(prepared).toMatchObject({
      unusable: ["input_0"],
      emptyReason: "input-type-rejected",
      inputProblem: "raster is not a valid input type for the Autark node.",
    });
  });
});

describe("loadableSource", () => {
  const source = (geoms: any[]) => ({
    type: "geojson" as const,
    geojsonObject: fc(geoms) as any,
    outputTableName: "input_0",
    coordinateFormat: "EPSG:4326",
  });

  test("a first feature without geometry trades places with the first that has one", () => {
    const { source: loaded, order } = loadableSource(source([null, null, point(2, 2), point(3, 3)]));
    expect((loaded.geojsonObject.features as any[]).map((f) => f.properties.value)).toEqual([2, 1, 0, 3]);
    // The table holds rows 2, 1, 0, 3; a map draws only 2 and 3.
    expect(order).toEqual({ load: [2, 1, 0, 3], map: [2, 3] });
  });

  test("a map pick and a highlight name the input's rows, not positions in what was drawn", () => {
    const { order } = loadableSource(source([point(0, 0), null, point(2, 2)]));
    expect(order).toEqual({ load: null, map: [0, 2] });
    // The second thing the map drew is input row 2...
    expect(inputRow(1, order.map)).toBe(2);
    // ...and a highlight on rows 1 and 2 lights map position 1 (row 1 is not drawn).
    expect(tablePositions([1, 2], order.map)).toEqual([1]);
    // A plot reads the table as loaded, so its positions are the rows.
    expect(inputRow(1, order.load)).toBe(1);
    expect(tablePositions([1, 2], order.load)).toEqual([1, 2]);
  });

  test("a table with geometry everywhere is left alone", () => {
    const plain = source([point(0, 0), point(1, 1)]);
    expect(loadableSource(plain)).toEqual({ source: plain, order: { load: null, map: null } });
  });
});

test("prepareAutkInput reads the input through the shared reader", async () => {
  mockFetchData.mockResolvedValue({ dataType: "geodataframe", data: fc([point(1, 1)]) });
  const prepared = await prepareAutkInput({ path: "art", dataType: "geodataframe" }, MAP_ON("input_0"));
  expect(mockFetchData).toHaveBeenCalledWith("art");
  expect(prepared.tables).toEqual(["input_0"]);
});

test("two upstream Autark nodes' layers of one name, as they arrive: each input draws its own (#744)", async () => {
  // An Autark node hands on a single layer under its name
  // (adapters/node/autkLayerMaterialize); here two copies of one node do.
  const rain = fc([point(1, 1)]);
  const wind = fc([point(2, 2), point(3, 3)]);
  mockFetchData.mockImplementation(async (path: string) => ({
    dataType: "geodataframe",
    data: path === "art-rain" ? rain : wind,
    layerName: "routes",
  }));
  const prepared = await prepareAutkInput(
    {
      dataType: "outputs",
      data: [{ path: "art-rain", dataType: "geodataframe" }, { path: "art-wind", dataType: "geodataframe" }],
    },
    MAP_ON("input_0", "input_1"),
  );
  const drawn = (name: string) => prepared.sources.find((s) => s.outputTableName === name)?.geojsonObject;
  expect(drawn("input_0")).toEqual(rain);
  expect(drawn("input_1")).toEqual(wind);
});

describe("a layer chip in the document reads the frame its input carries (#662)", () => {
  // The chips resolve against the scope the node builds (hook/useInputScope):
  // each wired circle with the value it holds, before any column is read.
  const scopeOf = (values: unknown[]) => ({
    widgets: [],
    shared: [],
    inputs: inputScopeFor(
      "map",
      values.map((_, slot) => ({
        source: `up-${slot}`, target: "map", sourceHandle: "out", targetHandle: slot === 0 ? "in" : `in_${slot}`,
      })),
      [],
      (slot) => values[slot],
      () => null,
      () => undefined,
    ),
  });
  const resolvedSpec = (text: string, values: unknown[]) => {
    const { code, problems } = resolveReferences(text, scopeOf(values), "json");
    expect(problems).toEqual([]);
    return JSON.parse(code);
  };
  const tables = (prepared: PreparedAutkInput) =>
    Object.fromEntries(prepared.sources.map((s) => [s.outputTableName, s.geojsonObject]));

  test("an input of one GeoDataFrame with no layer name is that layer, whatever the chip names", async () => {
    const grid = fc([point(1, 1), point(2, 2)]);
    mockFetchData.mockResolvedValue({ dataType: "geodataframe", data: grid });
    const input = { path: "art-grid", dataType: "geodataframe" };
    const spec = resolvedSpec('{"map": {"layerRefs": [{"dataRef": [!! input 0:anything !!]}]}}', [input]);
    const loaded = tables(await prepareAutkInput(input, spec));
    expect(Object.keys(loaded)).toContain(spec.map.layerRefs[0].dataRef);
    expect(loaded[spec.map.layerRefs[0].dataRef]).toEqual(grid);
  });

  test("on a node with several inputs, each chip reads the frame of the input it names", async () => {
    const parks = fc([point(1, 1)]);
    const roads = fc([point(2, 2), point(3, 3)]);
    mockFetchData.mockImplementation(async (path: string) => ({
      dataType: "geodataframe",
      data: path === "art-parks" ? parks : roads,
    }));
    const slots = [{ path: "art-parks", dataType: "geodataframe" }, { path: "art-roads", dataType: "geodataframe" }];
    const spec = resolvedSpec(
      '{"map": {"layerRefs": [{"dataRef": [!! input 1:roads !!]}, {"dataRef": [!! input 0:parks !!]}]}}',
      slots,
    );
    const loaded = tables(await prepareAutkInput({ dataType: "outputs", data: slots }, spec));
    const [first, second] = spec.map.layerRefs.map((ref: any) => ref.dataRef);
    expect(Object.keys(loaded)).toEqual(expect.arrayContaining([first, second]));
    expect(loaded[first]).toEqual(roads);
    expect(loaded[second]).toEqual(parks);
  });

  test("an input of several layers is still read by the layer's own name", async () => {
    const roads = fc([point(1, 1)]);
    mockFetchData.mockResolvedValue({
      dataType: "outputs",
      data: [
        { dataType: "geodataframe", data: roads, layerName: "table_osm_roads" },
        { dataType: "geodataframe", data: fc([point(5, 5)]), layerName: "table_osm_parks" },
      ],
    });
    const input = { path: "art-osm", dataType: "outputs" };
    const spec = resolvedSpec('{"map": {"layerRefs": [{"dataRef": [!! input 0:table_osm_roads !!]}]}}', [input]);
    expect(spec.map.layerRefs[0].dataRef).toBe("table_osm_roads");
    expect(tables(await prepareAutkInput(input, spec)).table_osm_roads).toEqual(roads);
  });
});
