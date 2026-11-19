/**
 * An Autark node's data section reads its input's tables: a heatmap bins, and
 * a join reads, a table the node's input carries, named as the node names its
 * input everywhere (`input_<k>`, or a layer's own name). Both loaders load each
 * such table into the section's database just before the first entry that
 * reads it, in that entry's workspace, and hand on what the section loads and
 * makes, an input table only when a join wrote its columns onto it.
 *
 * The sandbox's loader is the JavaScript `compileDataSpecToAutkDbJs` writes,
 * run here as the sandbox runs it: its imports dropped, autk-db stood in, and
 * the inputs the sandbox gives a JavaScript run (`__inputs`,
 * sandbox/util/js_wrapper.mjs), each as the sandbox hands it to node code. The
 * browser's loader is `loadSpecLayers`, handed the tables the node read of its
 * input (`autkSourcesFrom`).
 */
jest.mock("../../../services/api", () => ({ fetchData: (...a: any[]) => mockFetchData(...a) }));
// Virtual, as the other suites mock Autark: keyed by the package's name.
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_NAME: "autk",
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  AutkDb: function AutkDb() { return new mockTablesDb(); },
}), { virtual: true });
// The grammar's data entry with its own `enterWorkspace` and `tableKey`, and a
// stand-in data adapter. Plain, not virtual: every suite mocks a module one
// way, and this entry's one mock kind is plain (mockKinds.test.ts).
jest.mock("@urban-toolkit/autk-grammar/data", () => ({
  ...jest.requireActual("@urban-toolkit/autk-grammar/data"),
  createDataAdapter: (...args: any[]) => mockCreateDataAdapter(...args),
}));

const mockFetchData = jest.fn();

/** What the stand-in database was asked, in order. */
const mockCalls: any[][] = [];

const mockCreateDataAdapter = jest.fn((...args: any[]) => {
  // Every other source as the grammar's own adapter loads it.
  const grammar = jest.requireActual("@urban-toolkit/autk-grammar/data").createDataAdapter(...args);
  return {
    // As autk-grammar 5's adapter builds a heatmap: autk-db's buildHeatmap, with
    // the grammar's joinDataRef as autk-db's tableJoinName, in its workspace.
    resolveSource: jest.fn(async (db: any, source: any) => {
      if (source.type !== "heatmap") return grammar.resolveSource(db, source);
      await jest.requireActual("@urban-toolkit/autk-grammar/data").enterWorkspace(db, source.workspace);
      await db.buildHeatmap({
        tableJoinName: source.joinDataRef, near: source.near, outputTableName: source.outputTableName,
        grid: source.grid, groupBy: source.groupBy,
      });
      return db;
    }),
  };
});

/**
 * autk-db, as far as a loader sees it: each workspace holds its tables, a table
 * is found in the current workspace only, a heatmap bins a table there, and a
 * join writes a `joined` column onto its root table, counting the rows of the
 * joined one.
 */
class mockTablesDb {
  private workspace = "autk";
  private tables = new Map<string, Map<string, any>>();
  private rasters = new Map<string, any>();
  async init() { mockCalls.push(["init"]); }
  getCurrentWorkspace() { return this.workspace; }
  async setWorkspace(name: string) { this.workspace = name; }
  private current(): Map<string, any> {
    if (!this.tables.has(this.workspace)) this.tables.set(this.workspace, new Map());
    return this.tables.get(this.workspace)!;
  }
  async loadGeojson({ outputTableName, geojsonObject, coordinateFormat, layerType }: any) {
    mockCalls.push(["loadGeojson", outputTableName, this.workspace, coordinateFormat, layerType]);
    this.current().set(outputTableName, JSON.parse(JSON.stringify(geojsonObject)));
  }
  getLayersMetadata() {
    return [...this.current().keys()].map((name) => ({ name, type: "points", source: "geojson" }));
  }
  async getLayer(name: string) {
    const table = this.current().get(name);
    if (!table) throw new Error(`Table ${name} not found.`);
    return JSON.parse(JSON.stringify(table));
  }
  async spatialQuery({ tableRootName, tableJoinName }: any) {
    mockCalls.push(["spatialQuery", tableRootName, tableJoinName, this.workspace]);
    const root = this.current().get(tableRootName);
    const joined = this.current().get(tableJoinName);
    if (!root) throw new Error(`Table ${tableRootName} not found.`);
    if (!joined) throw new Error(`Table ${tableJoinName} not found.`);
    for (const feature of root.features) feature.properties = { ...feature.properties, joined: joined.features.length };
  }
  async buildHeatmap(params: any) {
    mockCalls.push(["buildHeatmap", params.tableJoinName, this.workspace]);
    const table = this.current().get(params.tableJoinName);
    if (!table) throw new Error(`Table ${params.tableJoinName} not found.`);
    this.rasters.set(`${this.workspace}.${params.outputTableName}`, { params, rows: table.features.length });
    return { name: params.outputTableName, type: "raster", source: "user" };
  }
  async getRaster(name: string) {
    const raster = this.rasters.get(`${this.workspace}.${name}`);
    if (!raster) throw new Error(`Table ${name} is not a compact raster table.`);
    return {
      type: "FeatureCollection",
      bbox: [-9755100, 5142000, -9753100, 5143000],
      features: [{
        type: "Feature",
        geometry: null,
        properties: {
          rasterResX: 2, rasterResY: 1,
          bands: [{ id: "band_1", label: `count_${raster.params.tableJoinName}` }],
          // Each cell counts every row of the table binned.
          band_1: Float32Array.from([raster.rows, raster.rows]),
        },
      }],
    };
  }
  getWorkspaceConfiguration() { return { coordinateFormat: "EPSG:3395", precisionGrid: 0.01 }; }
}

import {
  compileDataSpecToAutkDbJs,
  coordinateFormatOf,
  inputTablesFrom,
  sectionInputTables,
  sectionTableProblem,
} from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers, toPoolOutput } from "../../../adapters/node/autkLayerMaterialize";
import { autkSourcesFrom, readAutkInput, tableKeyOf } from "../../../utils/autkInput";
import { detectCoordinateFormat } from "../../../utils/geoCrs";
import CASES from "../../../adapters/node/autkSectionInputs.cases.json";

/** The grammar data entry's own `enterWorkspace` and `tableKey`, which the sandbox's code imports. */
const { enterWorkspace, tableKey } = jest.requireActual("@urban-toolkit/autk-grammar/data");

/** Points in Chicago, in EPSG:3395 metres, each marked so a test can tell tables apart. */
const points = (marker: string, count = 2, crs = true) => ({
  type: "FeatureCollection",
  ...(crs ? { crs: { type: "name", properties: { name: "urn:ogc:def:crs:EPSG::3395" } } } : {}),
  features: Array.from({ length: count }, (_, i) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [-9755000 + 100 * i, 5142500] },
    properties: { marker, i },
  })),
});

/** A heatmap of *table* in *workspace*. */
const heatmapOf = (table: string, out = "density", workspace?: string) => ({
  type: "heatmap", joinDataRef: table, outputTableName: out,
  near: { distance: 400 }, grid: { rows: 1, columns: 2 }, groupBy: [{ column: "*", aggregateFn: "count" }],
  ...(workspace ? { workspace } : {}),
});

/** The section's own table: roads it loads itself. */
const ROADS = { type: "geojson", outputTableName: "roads", coordinateFormat: "EPSG:3395", geojsonObject: points("roads", 3) };

/** The node's input as the browser reads it (an AutkSource), for the browser's loader. */
const inputTable = (name: string, collection: any, workspace?: string) => ({
  type: "geojson" as const,
  outputTableName: name,
  geojsonObject: collection,
  coordinateFormat: detectCoordinateFormat(collection),
  ...(workspace ? { workspace } : {}),
});

/** What the sandbox's code returns, run as the sandbox runs it, with *inputs* as the run's. */
async function sandboxLoad(sources: any[], inputs: Record<string, unknown> = {}): Promise<any[]> {
  const body = compileDataSpecToAutkDbJs(sources).replace(/^import [^\n]*\n/gm, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  return new AsyncFunction(
    "AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "createDataAdapter", "enterWorkspace", "tableKey", "__inputs", body,
  )(mockTablesDb, "EPSG:3395", mockCreateDataAdapter, enterWorkspace, tableKey, inputs);
}

/** The name each item a load handed on is under: a table's, or a raster's. */
const names = (out: any[]) => out.map((item: any) => item.name ?? item.layerName);

beforeEach(() => {
  mockCalls.length = 0;
  mockFetchData.mockReset();
  mockCreateDataAdapter.mockClear();
});

describe("the tables of the input a data section reads", () => {
  test.each(CASES.cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const spec: any = c.spec;
    expect(sectionInputTables(spec.data ?? []).map((t) => (t.workspace ? `${t.workspace}/${t.name}` : t.name)))
      .toEqual(c.reads);
  });
});

describe("a heatmap of an input table", () => {
  const SECTION = [heatmapOf("input_0")];

  test("the sandbox's loader loads the input table first, bins it, and hands on the heatmap alone", async () => {
    const out = await sandboxLoad(SECTION, { input_0: points("labels", 4) });
    expect(mockCalls.filter((call) => call[0] !== "init")).toEqual([
      ["loadGeojson", "input_0", "autk", "EPSG:3395", undefined],
      ["buildHeatmap", "input_0", "autk"],
    ]);
    expect(names(out)).toEqual(["density"]);
    expect(out[0].dataType).toBe("raster");
  });

  test("the browser's loader loads it from the tables the node read, and hands on the heatmap alone", async () => {
    const tables = await loadSpecLayers({ data: SECTION }, [inputTable("input_0", points("labels", 4))]);
    expect(mockCalls.filter((call) => call[0] !== "init")).toEqual([
      ["loadGeojson", "input_0", "autk", "EPSG:3395", undefined],
      ["buildHeatmap", "input_0", "autk"],
    ]);
    expect(tables.map((table) => [table.name, table.type])).toEqual([["density", "raster"]]);
    const handed = await toPoolOutput(tables, undefined, "heat-node");
    expect(handed.layerName).toBe("density");
  });

  test("after the section's own source, it is loaded just before the heatmap that bins it", async () => {
    const section = [ROADS, heatmapOf("input_0")];
    const expected = [
      ["loadGeojson", "roads", "autk", "EPSG:3395", undefined],
      ["loadGeojson", "input_0", "autk", "EPSG:3395", undefined],
      ["buildHeatmap", "input_0", "autk"],
    ];
    const fromSandbox = await sandboxLoad(section, { input_0: points("labels") });
    expect(mockCalls.filter((call) => call[0] !== "init")).toEqual(expected);
    expect(names(fromSandbox)).toEqual(["roads", "density"]);
    mockCalls.length = 0;
    const fromBrowser = await loadSpecLayers({ data: section }, [inputTable("input_0", points("labels"))]);
    expect(mockCalls.filter((call) => call[0] !== "init")).toEqual(expected);
    expect(fromBrowser.map((table) => table.name)).toEqual(["roads", "density"]);
  });

  test("a heatmap in a workspace bins the input's table of that workspace, loaded there", async () => {
    const section = [{ ...ROADS, workspace: "east" }, heatmapOf("labels", "density", "east")];
    const fromSandbox = await sandboxLoad(section, {
      // A layer an Autark node hands on from `east`, as the sandbox gives it to node code.
      input_0: { ...points("labels"), name: "labels", workspace: "east" },
    });
    expect(mockCalls.filter((call) => call[0] === "loadGeojson" || call[0] === "buildHeatmap")).toEqual([
      ["loadGeojson", "roads", "east", "EPSG:3395", undefined],
      ["loadGeojson", "labels", "east", "EPSG:3395", undefined],
      ["buildHeatmap", "labels", "east"],
    ]);
    expect(fromSandbox.map((item: any) => [item.name ?? item.layerName, item.workspace])).toEqual([
      ["roads", "east"], ["density", "east"],
    ]);
    const fromBrowser = await loadSpecLayers({ data: section }, [inputTable("labels", points("labels"), "east")]);
    expect(fromBrowser.map((table) => [table.name, table.workspace])).toEqual([["roads", "east"], ["density", "east"]]);
  });

  test("both loaders hand the heatmap on in the same envelope", async () => {
    const [fromSandbox] = await sandboxLoad(SECTION, { input_0: points("labels", 4) });
    const fromBrowser = await toPoolOutput(
      await loadSpecLayers({ data: SECTION }, [inputTable("input_0", points("labels", 4))]), undefined, "heat-node",
    );
    expect(fromSandbox).toEqual(fromBrowser);
  });
});

describe("a join with an input table", () => {
  test("joins the input's table onto the section's own, and hands on the section's table alone", async () => {
    const section = [ROADS, { type: "join", dataRef: "roads", joinDataRef: "input_0" }];
    const fromSandbox = await sandboxLoad(section, { input_0: points("labels", 4) });
    expect(mockCalls.filter((call) => call[0] !== "init")).toEqual([
      ["loadGeojson", "roads", "autk", "EPSG:3395", undefined],
      ["loadGeojson", "input_0", "autk", "EPSG:3395", undefined],
      ["spatialQuery", "roads", "input_0", "autk"],
    ]);
    expect(names(fromSandbox)).toEqual(["roads"]);
    expect(fromSandbox[0].geojson.features.map((f: any) => f.properties.joined)).toEqual([4, 4, 4]);

    const fromBrowser = await loadSpecLayers({ data: section }, [inputTable("input_0", points("labels", 4))]);
    expect(fromBrowser.map((table) => table.name)).toEqual(["roads"]);
    expect(fromBrowser[0].geojson.features.map((f: any) => f.properties.joined)).toEqual([4, 4, 4]);
  });

  test("an input table a join writes its columns onto is what the join made, and is handed on", async () => {
    const section = [ROADS, { type: "join", dataRef: "input_0", joinDataRef: "roads" }];
    const fromSandbox = await sandboxLoad(section, { input_0: points("blocks", 2) });
    expect(names(fromSandbox)).toEqual(["roads", "input_0"]);
    expect(fromSandbox[1].geojson.features.map((f: any) => f.properties.joined)).toEqual([3, 3]);

    const fromBrowser = await loadSpecLayers({ data: section }, [inputTable("input_0", points("blocks", 2))]);
    expect(fromBrowser.map((table) => table.name)).toEqual(["roads", "input_0"]);
    expect(fromBrowser[1].geojson.features.map((f: any) => f.properties.joined)).toEqual([3, 3]);
  });
});

describe("a table neither the data section loads nor the input carries", () => {
  const SAID = 'The heatmap "density" bins "roads", a table its data section does not load '
    + "and the node's input does not carry.";

  test("fails the sandbox's load before anything loads, naming the table", async () => {
    await expect(sandboxLoad([heatmapOf("roads")], { input_0: points("labels") })).rejects.toThrow(SAID);
    expect(mockCalls).toEqual([]);
  });

  test("fails the browser's load before anything loads, naming the table", async () => {
    await expect(loadSpecLayers({ data: [heatmapOf("roads")] }, [inputTable("input_0", points("labels"))]))
      .rejects.toThrow(SAID);
    expect(mockCalls).toEqual([]);
  });

  test("a join's table is named with the join, by its key in the join's workspace", async () => {
    const section = [{ ...ROADS, workspace: "east" }, { type: "join", dataRef: "roads", joinDataRef: "labels", workspace: "east" }];
    const said = 'The join of "east/labels" onto "east/roads" reads "east/labels", a table its data section does '
      + "not load and the node's input does not carry.";
    await expect(sandboxLoad(section, { input_0: points("labels") })).rejects.toThrow(said);
    await expect(loadSpecLayers({ data: section }, [inputTable("labels", points("labels"))])).rejects.toThrow(said);
    expect(mockCalls).toEqual([]);
  });

  test("a join that reads a table the section loads only after it fails both loads, saying to list that source first", async () => {
    const section = [{ type: "join", dataRef: "roads", joinDataRef: "input_0" }, ROADS];
    const said = 'The join of "input_0" onto "roads" reads "roads" before its data section loads that table: '
      + 'list the source of "roads" first.';
    expect(sectionTableProblem(section)).toBe(said);
    await expect(sandboxLoad(section, { input_0: points("labels") })).rejects.toThrow(said);
    await expect(loadSpecLayers({ data: section }, [inputTable("input_0", points("labels"))])).rejects.toThrow(said);
    expect(mockCalls).toEqual([]);
  });
});

test("guard: a data section that reads no input table compiles with no input part", () => {
  const code = compileDataSpecToAutkDbJs([ROADS, heatmapOf("roads")]);
  for (const part of ["__inputs", "__inputTables", "__runs", "__handedOn"]) expect(code).not.toContain(part);
  expect(code).toContain("for (const source of __sources) {");
});

// The sandbox's loader finds the input's tables by the names the node reads
// its input by (autkSourcesFrom), from the inputs as the sandbox hands them to
// node code (worker._to_js_value): each case gives the input the browser reads
// (what /get answers for each reference) and the one the sandbox gives the run.
describe("the sandbox's loader names the input's tables as the node does", () => {
  const roadsRecord = { name: "loop_roads", type: "roads", geojson: points("loop_roads") };
  const parksRecord = { name: "loop_parks", type: "parks", geojson: points("loop_parks") };
  const asListEnvelope = (...records: any[]) => ({
    dataType: "list", data: records.map((record) => ({ dataType: "dict", data: record })),
  });
  const CASES_BY_INPUT: Array<{
    name: string; input: any; fetched: Record<string, any>; given: Record<string, any>; found: Record<string, string>;
    absent: string[];
  }> = [
    {
      name: "a Python node's GeoDataFrame is input_0",
      input: { path: "gdf", dataType: "geodataframe" },
      fetched: { gdf: { dataType: "geodataframe", data: points("python") } },
      given: { input_0: points("python") },
      found: { input_0: "python" },
      absent: ["python"],
    },
    {
      name: "an Autark node's layer list keeps each layer's name",
      input: { path: "layers", dataType: "list" },
      fetched: { layers: asListEnvelope(roadsRecord, parksRecord) },
      given: { input_0: [roadsRecord, parksRecord] },
      found: { loop_roads: "loop_roads", loop_parks: "loop_parks" },
      absent: ["input_0"],
    },
    {
      name: "two inputs: a GeoDataFrame, and one named layer, also input_1",
      input: { dataType: "outputs", data: [{ path: "gdf", dataType: "geodataframe" }, { path: "one", dataType: "list" }] },
      fetched: { gdf: { dataType: "geodataframe", data: points("python") }, one: asListEnvelope(roadsRecord) },
      given: { input_0: points("python"), input_1: [roadsRecord] },
      found: { input_0: "python", loop_roads: "loop_roads", input_1: "loop_roads" },
      absent: ["loop_parks"],
    },
    {
      name: "a name two inputs bring is the first input's, and the second's input_<k>",
      input: { dataType: "outputs", data: [{ path: "a", dataType: "list" }, { path: "b", dataType: "list" }] },
      fetched: {
        a: asListEnvelope(roadsRecord),
        b: asListEnvelope({ ...roadsRecord, geojson: points("second_roads") }),
      },
      given: { input_0: [roadsRecord], input_1: [{ ...roadsRecord, geojson: points("second_roads") }] },
      found: { loop_roads: "loop_roads", input_0: "loop_roads", input_1: "second_roads" },
      absent: [],
    },
    {
      name: "a Python tuple's frames are input_0 and input_1",
      input: { path: "tuple", dataType: "outputs" },
      fetched: {
        tuple: { dataType: "outputs", data: [
          { dataType: "geodataframe", data: points("first") }, { dataType: "geodataframe", data: points("second") },
        ] },
      },
      given: { input_0: [points("first"), points("second")] },
      found: { input_0: "first", input_1: "second" },
      absent: [],
    },
  ];

  test.each(CASES_BY_INPUT.map((c) => [c.name, c] as const))("%s", async (_name, c) => {
    mockFetchData.mockImplementation(async (path: string) => c.fetched[path]);
    const read = await readAutkInput(c.input);
    for (const [table, marker] of Object.entries(c.found)) {
      const spec = { data: [heatmapOf(table)] };
      const fromBrowser = autkSourcesFrom(read, spec).sources.find((source) => tableKeyOf(source) === table);
      expect([table, (fromBrowser?.geojsonObject as any)?.features?.[0]?.properties?.marker]).toEqual([table, marker]);
      const [fromSandbox] = inputTablesFrom(c.given, sectionInputTables(spec.data));
      expect([table, fromSandbox.rows.features[0].properties.marker]).toEqual([table, marker]);
    }
    for (const table of c.absent) {
      const spec = { data: [heatmapOf(table)] };
      expect(autkSourcesFrom(read, spec).sources.some((source) => tableKeyOf(source) === table)).toBe(false);
      expect(() => inputTablesFrom(c.given, sectionInputTables(spec.data))).toThrow("does not carry");
    }
  });
});

describe("the sandbox's loader gives an input table the coordinate format the node gives it", () => {
  const COLLECTIONS: Array<[string, any]> = [
    ["a CRS named", points("named")],
    ["WGS84 named", { ...points("wgs"), crs: { type: "name", properties: { name: "urn:ogc:def:crs:EPSG::4326" } } }],
    ["no CRS, projected coordinates", points("projected", 2, false)],
    ["no CRS, longitude and latitude", {
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: { type: "Point", coordinates: [-87.63, 41.88] }, properties: {} }],
    }],
    ["no geometry in the first rows", {
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: null, properties: {} },
        { type: "Feature", geometry: { type: "GeometryCollection", geometries: [{ type: "Point", coordinates: [-9755000, 5142000] }] }, properties: {} },
      ],
    }],
    ["no rows", { type: "FeatureCollection", features: [] }],
  ];

  test.each(COLLECTIONS)("%s", (_name, collection) => {
    expect(coordinateFormatOf(collection)).toBe(detectCoordinateFormat(collection));
  });
});
