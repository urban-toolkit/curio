/**
 * A heatmap source loads on both of an Autark node's loaders as the grammar
 * loads it, through autk-grammar's own data adapter: the sandbox's
 * (compileDataSpecToAutkDbJs), which a run on the server posts, from the
 * grammar's `./data` entry, and the in-browser fallback (loadSpecLayers), from
 * its main entry. Each reads the raster table back with the grid its cells lie
 * on and hands it on after the layers, in Curio's raster envelope
 * (utils/raster/rasterWire), the same on both.
 */
import { compileDataSpecToAutkDbJs } from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers, toPoolOutput } from "../../../adapters/node/autkLayerMaterialize";
import { decodeRasterEnvelope } from "../../../utils/raster/rasterWire";

jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
// Virtual, as the other suites mock Autark: keyed by the package's name.
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  AutkDb: jest.fn().mockImplementation(() => new mockAutkDb()),
}), { virtual: true });
jest.mock("@urban-toolkit/autk-grammar", () => ({
  createDataAdapter: (...args: any[]) => mockCreateDataAdapter(...args),
}), { virtual: true });

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

/** What the grammar's adapter was asked to load, and the heatmaps it built. */
const mockResolved: Array<{ db: any; source: any }> = [];
const mockBuilt: any[] = [];
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

class mockAutkDb {
  heatmaps = new Map<string, any>();
  init() { return Promise.resolve(); }
  loadGeojson() { return Promise.resolve(); }
  getLayersMetadata() { return [{ name: "readings", type: "points", source: "geojson", columns: [] }]; }
  getLayer() { return Promise.resolve(JSON.parse(JSON.stringify(READINGS))); }
  getWorkspaceConfiguration() { return { coordinateFormat: "EPSG:3395", precisionGrid: 0.01 }; }
  getCurrentWorkspace() { return "autk"; }
  buildHeatmap(params: any) {
    if (mockBuildFails) return Promise.reject(mockBuildFails);
    mockBuilt.push(params);
    this.heatmaps.set(params.outputTableName, params);
    return Promise.resolve({ name: params.outputTableName, type: "raster", source: "user" });
  }
  getRaster(name: string) {
    if (!this.heatmaps.has(name)) return Promise.reject(new Error(`Table ${name} is not a compact raster table.`));
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

/** What the sandbox's code returns, run as the sandbox runs it. */
async function sandboxLoad(sources: any[]): Promise<any[]> {
  const body = compileDataSpecToAutkDbJs(sources).replace(/^import [^\n]*\n/gm, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  return new AsyncFunction("AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "createDataAdapter", body)(
    mockAutkDb, "EPSG:3395", mockCreateDataAdapter,
  );
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
  test("builds a heatmap through the main entry's data adapter, in the database it loaded the table into", async () => {
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
