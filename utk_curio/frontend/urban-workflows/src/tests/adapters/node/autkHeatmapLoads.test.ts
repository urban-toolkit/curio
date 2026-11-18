/**
 * A heatmap source loads on both of an Autark node's loaders as the grammar
 * loads it, through autk-grammar's own data adapter, from the grammar's
 * `./data` entry: the sandbox's (compileDataSpecToAutkDbJs), which a run on the
 * server posts, and the in-browser fallback (loadSpecLayers). Each reads the
 * raster table back with the grid its cells lie on and hands it on after the
 * layers, in Curio's raster envelope (utils/raster/rasterWire), the same on
 * both. A heatmap in a workspace is built there and handed on with it.
 */
import { compileDataSpecToAutkDbJs, heatmapTableProblem } from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers, toPoolOutput } from "../../../adapters/node/autkLayerMaterialize";
import { decodeRasterEnvelope } from "../../../utils/raster/rasterWire";

jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
// Virtual, as the other suites mock Autark: keyed by the package's name.
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_NAME: "autk",
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  AutkDb: jest.fn().mockImplementation(() => new mockAutkDb()),
}), { virtual: true });
// The grammar's data entry with its own `enterWorkspace` and `tableKey`, and a
// stand-in data adapter. Plain, not virtual: the suites that load this entry
// unmocked key it by its file, and a Jest worker's resolver keeps the first key
// it works out for a file's require (autkGrammarBuildMocks.test.ts).
jest.mock("@urban-toolkit/autk-grammar/data", () => ({
  ...jest.requireActual("@urban-toolkit/autk-grammar/data"),
  createDataAdapter: (...args: any[]) => mockCreateDataAdapter(...args),
}));

// Readings in Chicago, in EPSG:3395 metres, as autk-db's workspace holds them.
const READINGS = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: { type: "Point", coordinates: [-9755100, 5142000] }, properties: { db: 61 } },
    { type: "Feature", geometry: { type: "Point", coordinates: [-9753600, 5143000] }, properties: { db: 74 } },
  ],
};

// The heatmap autk-db 4.1.1 builds over the workspace's extent and getRaster
// gives: 3 columns by 2 rows, rows from south to north, the band labelled
// `<aggregateFn>_<table>`.
const BBOX = [-9755100, 5142000, -9753600, 5143000];
const COUNTS = [0, 1, 2, 2, 1, 0];

/** What the grammar's adapter was asked to load, the heatmaps it built, and the workspace each was built in. */
const mockResolved: Array<{ db: any; source: any }> = [];
const mockBuilt: any[] = [];
const mockBuiltIn: string[] = [];
/** A heatmap build that fails, when set. */
let mockBuildFails: Error | null = null;

const mockCreateDataAdapter = jest.fn((..._args: any[]) => ({
  // As autk-grammar 5's adapter loads a heatmap: autk-db's buildHeatmap, with
  // the grammar's joinDataRef as autk-db's tableJoinName.
  resolveSource: jest.fn(async (db: any, source: any) => {
    mockResolved.push({ db, source });
    if (source.type === "heatmap") {
      await db.buildHeatmap({
        tableJoinName: source.joinDataRef,
        near: source.near,
        outputTableName: source.outputTableName,
        grid: source.grid,
        groupBy: source.groupBy,
      });
    }
    return db;
  }),
}));

// Sound levels in EPSG:3395 metres, in a box 3 km by 2 km at the Chicago Loop
// binned into 3 by 2 cells of 1 km, as test_autk_server_data_load.py builds
// them with autk-db itself: two readings at the box's corners, 707 m from
// every cell's center, past the 600 m a cell reaches, and the others within
// 100 m of their own cell's center.
const LOOP = [-9755000, 5106000];
const LEVELS = [
  [0, 0, 40], [3000, 2000, 95],
  [500, 500, 50],
  [1500, 500, 60], [1600, 500, 70],
  [500, 1500, 55], [600, 1500, 58], [400, 1500, 61],
  [1500, 1500, 62], [1600, 1500, 66], [1400, 1500, 70], [1500, 1600, 74],
  [2500, 1500, 80], [2500, 1600, 84],
];
const LEVEL_SOURCE = {
  type: "geojson",
  outputTableName: "levels",
  coordinateFormat: "EPSG:3395",
  geojsonObject: {
    type: "FeatureCollection",
    features: LEVELS.map(([east, north, db]) => ({
      type: "Feature", geometry: { type: "Point", coordinates: [LOOP[0] + east, LOOP[1] + north] }, properties: { db },
    })),
  },
};
const LEVEL_BBOX = [LOOP[0], LOOP[1], LOOP[0] + 3000, LOOP[1] + 2000];
// What autk-db builds from them, a band per aggregate, rows from south to
// north: the readings within 600 m of a cell's center counted, weighted
// 1 / (distance + 1) each, or their levels summed, averaged, or their least
// and greatest; 0 where none is near.
const LEVEL_CELLS: Record<string, number[]> = {
  count: [1, 2, 0, 3, 4, 2],
  weighted: [1, 1 + 1 / 101, 0, 1 + 2 / 101, 1 + 3 / 101, 1 + 1 / 101],
  sum: [50, 130, 0, 174, 272, 164],
  avg: [50, 65, 0, 58, 68, 82],
  min: [50, 60, 0, 55, 62, 80],
  max: [50, 70, 0, 61, 74, 84],
};
const AGGREGATES = ["count", "weighted", "sum", "avg", "min", "max"];
/** A heatmap of the levels with a band for each of *aggregates*. */
const levelHeatmap = (aggregates: string[]) => ({
  type: "heatmap",
  joinDataRef: "levels",
  outputTableName: "noise",
  near: { distance: 600 },
  grid: { rows: 2, columns: 3 },
  groupBy: aggregates.map((fn) => ({ column: fn === "count" || fn === "weighted" ? "*" : "db", aggregateFn: fn })),
});

class mockAutkDb {
  /** The workspace the database works in; autk-db finds a table in it alone. */
  workspace = "autk";
  heatmaps = new Map<string, any>();
  /** Each workspace's tables. */
  layers = new Map<string, string[]>();
  init() { return Promise.resolve(); }
  getCurrentWorkspace() { return this.workspace; }
  setWorkspace(name: string) { this.workspace = name; return Promise.resolve(); }
  loadGeojson(params: any) {
    this.layers.set(this.workspace, [...(this.layers.get(this.workspace) ?? []), params.outputTableName]);
    return Promise.resolve();
  }
  getLayersMetadata() {
    const names = this.layers.size ? (this.layers.get(this.workspace) ?? []) : ["readings"];
    return names.map((name) => ({ name, type: "points", source: "geojson", columns: [] }));
  }
  getLayer() { return Promise.resolve(JSON.parse(JSON.stringify(READINGS))); }
  getWorkspaceConfiguration() { return { coordinateFormat: "EPSG:3395", precisionGrid: 0.01 }; }
  buildHeatmap(params: any) {
    if (mockBuildFails) return Promise.reject(mockBuildFails);
    mockBuilt.push(params);
    mockBuiltIn.push(this.workspace);
    this.heatmaps.set(`${this.workspace}.${params.outputTableName}`, params);
    return Promise.resolve({ name: params.outputTableName, type: "raster", source: "user" });
  }
  getRaster(name: string) {
    const key = `${this.workspace}.${name}`;
    if (!this.heatmaps.has(key)) return Promise.reject(new Error(`Table ${name} is not a compact raster table.`));
    const params = this.heatmaps.get(key);
    if (params.tableJoinName === "levels") {
      // As autk-db labels a heatmap's bands: `<aggregateFn>_<table>`, one per groupBy entry.
      const bands = params.groupBy.map((group: any, index: number) => ({
        id: `band_${index + 1}`, label: `${group.aggregateFn}_${params.tableJoinName}`,
      }));
      return Promise.resolve({
        type: "FeatureCollection",
        bbox: [...LEVEL_BBOX],
        features: [{
          type: "Feature",
          geometry: null,
          properties: {
            rasterResX: 3,
            rasterResY: 2,
            bands,
            originalRasterResX: 3,
            originalRasterResY: 2,
            ...Object.fromEntries(params.groupBy.map((group: any, index: number) => [
              `band_${index + 1}`, Float32Array.from(LEVEL_CELLS[group.aggregateFn]),
            ])),
          },
        }],
      });
    }
    return Promise.resolve({
      type: "FeatureCollection",
      bbox: [...BBOX],
      features: [{
        type: "Feature",
        geometry: null,
        properties: {
          rasterResX: 3,
          rasterResY: 2,
          bands: [{ id: "band_1", label: "count_readings" }],
          originalRasterResX: 3,
          originalRasterResY: 2,
          band_1: Float32Array.from(COUNTS),
        },
      }],
    });
  }
}

const HEATMAP = {
  type: "heatmap",
  joinDataRef: "readings",
  outputTableName: "density",
  near: { distance: 400 },
  grid: { rows: 2, columns: 3 },
  groupBy: [{ column: "*", aggregateFn: "count" }],
};
const SOURCES = [
  { type: "geojson", outputTableName: "readings", geojsonObject: READINGS, coordinateFormat: "EPSG:3395" },
  HEATMAP,
];

/** The grid the heatmap's cells lie on, over its extent, north up. */
const GRID = { crs: "EPSG:3395", width: 3, height: 2, originX: -9755100, originY: 5143000, resX: 500, resY: -500 };

const IMPORT_AUTK_DB = "import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';";
const IMPORT_GRAMMAR_DATA = "import { createDataAdapter } from '@urban-toolkit/autk-grammar/data';";

/** The grammar data entry's own `enterWorkspace` and `tableKey`, which the sandbox's code imports. */
const { enterWorkspace, tableKey } = jest.requireActual("@urban-toolkit/autk-grammar/data");

/** What the sandbox's code returns, run as the sandbox runs it. */
async function sandboxLoad(sources: any[]): Promise<any[]> {
  const body = compileDataSpecToAutkDbJs(sources).replace(/^import [^\n]*\n/gm, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  return new AsyncFunction(
    "AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "createDataAdapter", "enterWorkspace", "tableKey", body,
  )(mockAutkDb, "EPSG:3395", mockCreateDataAdapter, enterWorkspace, tableKey);
}

/** A raster envelope's collection, or the reason it cannot be read. */
function collectionIn(envelope: any): any {
  const decoded = decodeRasterEnvelope(envelope);
  if (!("collection" in decoded)) throw new Error(decoded.problem);
  return decoded.collection;
}

beforeEach(() => {
  mockResolved.length = 0;
  mockBuilt.length = 0;
  mockBuiltIn.length = 0;
  mockBuildFails = null;
  mockCreateDataAdapter.mockClear();
});

describe("the sandbox's loader", () => {
  test("imports the grammar's ./data entry, after autk-db, for a document with a heatmap", () => {
    const code = compileDataSpecToAutkDbJs(SOURCES);
    expect(code.match(/^import [^\n]*$/gm)).toEqual([IMPORT_AUTK_DB, IMPORT_GRAMMAR_DATA]);
  });

  test("guard: a document with no heatmap compiles with autk-db's import alone", () => {
    const code = compileDataSpecToAutkDbJs([SOURCES[0]]);
    expect(code.match(/^import [^\n]*$/gm)).toEqual([IMPORT_AUTK_DB]);
    expect(code).not.toContain("createDataAdapter");
  });

  test("builds a heatmap through the grammar's data adapter, in the database it loaded the table into", async () => {
    await sandboxLoad(SOURCES);
    expect(mockCreateDataAdapter).toHaveBeenCalledTimes(1);
    expect(mockResolved.map(({ source }) => source)).toEqual([HEATMAP]);
    expect(mockResolved[0].db).toBeInstanceOf(mockAutkDb);
    expect(mockBuilt).toEqual([{
      tableJoinName: "readings", near: { distance: 400 }, outputTableName: "density",
      grid: { rows: 2, columns: 3 }, groupBy: [{ column: "*", aggregateFn: "count" }],
    }]);
  });

  test("hands the heatmap on after the layers, as a raster in its envelope, on the grid its cells lie on", async () => {
    const out = await sandboxLoad(SOURCES);
    expect(out.map((table: any) => table.name ?? table.layerName)).toEqual(["readings", "density"]);
    const [, heat] = out;
    expect(heat.dataType).toBe("raster");
    const collection = collectionIn(heat);
    expect(collection.grid).toEqual(GRID);
    expect(collection.bbox).toEqual(BBOX);
    const properties = collection.features[0].properties;
    expect(properties.bands).toEqual([{ id: "band_1", label: "count_readings" }]);
    expect(Array.from(properties.band_1 as Float32Array)).toEqual(COUNTS);
  });

  test("a heatmap that fails to build fails the load, naming it", async () => {
    mockBuildFails = new Error("Table readings not found.");
    await expect(sandboxLoad(SOURCES)).rejects.toThrow(
      "autk data load produced 1 fewer table(s) than the spec asked for - missing: density (heatmap: Table readings not found.)",
    );
  });
});

describe("the in-browser loader", () => {
  test("builds a heatmap through the data entry's data adapter, in the database it loaded the table into", async () => {
    await loadSpecLayers({ data: SOURCES });
    expect(mockCreateDataAdapter).toHaveBeenCalledTimes(1);
    expect(mockResolved.map(({ source }) => source)).toEqual([HEATMAP]);
    expect(mockResolved[0].db).toBeInstanceOf(mockAutkDb);
    expect(mockBuilt.map((params) => params.outputTableName)).toEqual(["density"]);
  });

  test("reads the heatmap back after the layers, as a raster with the grid its cells lie on", async () => {
    const tables: any[] = await loadSpecLayers({ data: SOURCES });
    expect(tables.map((table) => [table.name, table.type])).toEqual([["readings", "points"], ["density", "raster"]]);
    const heat = tables[1].geojson;
    expect(heat.grid).toEqual(GRID);
    expect(heat.features[0].properties.bands).toEqual([{ id: "band_1", label: "count_readings" }]);
    expect(Array.from(heat.features[0].properties.band_1)).toEqual(COUNTS);
  });

  test("hands the heatmap on after the layers, as a raster in its envelope", async () => {
    const out = await toPoolOutput(await loadSpecLayers({ data: SOURCES }), undefined, "heat-node");
    expect(out.dataType).toBe("outputs");
    expect(out.data.map((item: any) => [item.dataType, item.layerName])).toEqual([
      ["geodataframe", "readings"],
      ["raster", "density"],
    ]);
    const collection = collectionIn(out.data[1]);
    expect(collection.grid).toEqual(GRID);
    expect(Array.from(collection.features[0].properties.band_1 as Float32Array)).toEqual(COUNTS);
  });

  test("a heatmap that fails to build fails the load, naming it", async () => {
    mockBuildFails = new Error("Table readings not found.");
    await expect(loadSpecLayers({ data: SOURCES })).rejects.toThrow(
      "autk data load produced 1 fewer table(s) than the spec asked for - missing: density (heatmap: Table readings not found.)",
    );
  });
});

test("both loaders hand the heatmap on in the same envelope", async () => {
  const [, fromSandbox] = await sandboxLoad(SOURCES);
  const fromBrowser = (await toPoolOutput(await loadSpecLayers({ data: SOURCES }), undefined, "heat-node")).data[1];
  expect(fromSandbox).toEqual(fromBrowser);
});

// A data section loads its own sources into a database of its own, so a
// heatmap bins only a table one of them loads before it: never the node's
// input. Both loaders say so, naming the table, before they load anything.
describe("a heatmap of a table its data section does not load", () => {
  const OF_THE_INPUT = { ...HEATMAP, joinDataRef: "input_0" };
  const SAID = 'The heatmap "density" bins "input_0", a table its data section does not load: '
    + "a data section loads only its own sources, not the node's input.";

  test("fails the sandbox's load before anything loads, naming the table", async () => {
    await expect(sandboxLoad([SOURCES[0], OF_THE_INPUT])).rejects.toThrow(SAID);
    expect(mockBuilt).toEqual([]);
  });

  test("fails the in-browser load before anything loads, naming the table", async () => {
    await expect(loadSpecLayers({ data: [SOURCES[0], OF_THE_INPUT] })).rejects.toThrow(SAID);
    expect(mockBuilt).toEqual([]);
  });

  test("one listed before the source of its table fails both loads, saying to list that source first", async () => {
    const early = [HEATMAP, SOURCES[0]];
    const said = 'The heatmap "density" bins "readings" before its data section loads that table: '
      + 'list the source of "readings" first.';
    await expect(sandboxLoad(early)).rejects.toThrow(said);
    await expect(loadSpecLayers({ data: early })).rejects.toThrow(said);
    expect(mockBuilt).toEqual([]);
  });
});

// The database is a stand-in here, so these pin the loaders' part for every
// aggregate: the heatmap reaches autk-db as written, and each band it builds
// is handed on under the label autk-db gives it, with its cells. autk-db's own
// part, the cells' values, is test_autk_server_data_load.py's and the e2e's.
describe("every aggregate", () => {
  /** The heatmap each loader hands on for *sources*: the sandbox's, then the browser's. */
  async function bothLoaders(sources: any[]): Promise<any[]> {
    const fromSandbox = (await sandboxLoad(sources)).find((item: any) => item.dataType === "raster");
    const fromBrowser = (await toPoolOutput(await loadSpecLayers({ data: sources }), undefined, "heat-node"))
      .data.find((item: any) => item.dataType === "raster");
    return [fromSandbox, fromBrowser];
  }

  test.each(AGGREGATES)("guard: both loaders build a %s heatmap and hand on its band, labelled as autk-db labels it, with its cells", async (fn) => {
    const heatmap = levelHeatmap([fn]);
    const handed = await bothLoaders([LEVEL_SOURCE, heatmap]);

    expect(mockBuilt.map((params) => [params.tableJoinName, params.groupBy])).toEqual([
      ["levels", heatmap.groupBy], ["levels", heatmap.groupBy],
    ]);
    for (const envelope of handed) {
      expect(envelope.layerName).toBe("noise");
      const collection = collectionIn(envelope);
      expect(collection.bbox).toEqual(LEVEL_BBOX);
      expect(collection.grid).toEqual({
        crs: "EPSG:3395", width: 3, height: 2, originX: LOOP[0], originY: LOOP[1] + 2000, resX: 1000, resY: -1000,
      });
      const properties = collection.features[0].properties;
      expect(properties.bands).toEqual([{ id: "band_1", label: `${fn}_levels` }]);
      expect(Array.from(properties.band_1 as Float32Array)).toEqual(Array.from(Float32Array.from(LEVEL_CELLS[fn])));
    }
  });

  test("guard: both loaders hand on a heatmap of every aggregate with a band each, in the order it names them", async () => {
    const handed = await bothLoaders([LEVEL_SOURCE, levelHeatmap(AGGREGATES)]);

    expect(handed[0]).toEqual(handed[1]);
    const properties = collectionIn(handed[0]).features[0].properties;
    expect(properties.bands).toEqual(AGGREGATES.map((fn, index) => ({ id: `band_${index + 1}`, label: `${fn}_levels` })));
    AGGREGATES.forEach((fn, index) => {
      expect(Array.from(properties[`band_${index + 1}`] as Float32Array)).toEqual(
        Array.from(Float32Array.from(LEVEL_CELLS[fn])),
      );
    });
  });
});

// A heatmap in a workspace (autk-grammar 5.0.0's `workspace`) is built there,
// bins a table of that workspace, and is handed on with it, as a table is. Its
// data section imports all it needs of the grammar's data entry in one line.
describe("a heatmap in a workspace", () => {
  const IN_EAST = [{ ...SOURCES[0], workspace: "east" }, { ...HEATMAP, workspace: "east" }];

  test("the sandbox's code imports the data adapter and the workspace functions in one line", () => {
    expect(compileDataSpecToAutkDbJs(IN_EAST).match(/^import [^\n]*$/gm)).toEqual([
      IMPORT_AUTK_DB,
      "import { createDataAdapter, enterWorkspace, tableKey } from '@urban-toolkit/autk-grammar/data';",
    ]);
  });

  test("both loaders build it in its workspace and hand it on with it, after its table", async () => {
    const fromSandbox = await sandboxLoad(IN_EAST);
    expect(fromSandbox.map((item: any) => [item.name ?? item.layerName, item.workspace])).toEqual([
      ["readings", "east"], ["density", "east"],
    ]);
    const tables: any[] = await loadSpecLayers({ data: IN_EAST });
    expect(tables.map((table) => [table.name, table.type, table.workspace])).toEqual([
      ["readings", "points", "east"], ["density", "raster", "east"],
    ]);
    expect(mockBuiltIn).toEqual(["east", "east"]);

    const fromBrowser = (await toPoolOutput(tables, undefined, "heat-node")).data[1];
    expect(fromBrowser.workspace).toBe("east");
    expect(fromSandbox[1]).toEqual(fromBrowser);
    expect(collectionIn(fromBrowser).grid).toEqual(GRID);
  });

  test("one that bins a table of another workspace fails both loads, naming each by its key", async () => {
    const elsewhere = [SOURCES[0], { ...HEATMAP, workspace: "east" }];
    const said = 'The heatmap "east/density" bins "east/readings", a table its data section does not load: '
      + "a data section loads only its own sources, not the node's input.";
    expect(heatmapTableProblem(elsewhere)).toBe(said);
    await expect(sandboxLoad(elsewhere)).rejects.toThrow(said);
    await expect(loadSpecLayers({ data: elsewhere })).rejects.toThrow(said);
    expect(mockBuilt).toEqual([]);
  });
});
