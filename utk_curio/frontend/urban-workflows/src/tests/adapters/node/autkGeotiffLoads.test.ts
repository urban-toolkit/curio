/**
 * A geotiff source loads on both of an Autark node's loaders as the grammar
 * loads it, through autk-grammar's own data adapter, from the grammar's
 * `./data` entry, which hands autk-db's `loadGeoTiff` the source as the
 * document writes it: the sandbox's loader (compileDataSpecToAutkDbJs), which a
 * run on the server posts, and the in-browser fallback (loadSpecLayers). A file
 * of the repository is named by its path, as a PBF extract is, and fetched from
 * the backend's `/file/` route; a URL is fetched as written. Each loader reads
 * the raster back with the grid its cells lie on and hands it on after the
 * layers, in Curio's raster envelope (utils/raster/rasterWire), the same on
 * both. A GeoTIFF in a workspace is loaded there and handed on with it, as a
 * heatmap is (autkHeatmapLoads.test.ts).
 */
import {
  SANDBOX_BACKEND_URL_TOKEN,
  compileDataSpecToAutkDbJs,
  resolveDataSourceUrls,
} from "../../../adapters/node/autkDataCompile";
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
// stand-in data adapter. Plain, as every suite mocks this entry: one mock kind
// for a module across the suites (mockKinds.test.ts).
jest.mock("@urban-toolkit/autk-grammar/data", () => ({
  ...jest.requireActual("@urban-toolkit/autk-grammar/data"),
  createDataAdapter: (...args: any[]) => mockCreateDataAdapter(...args),
}));

// The raster's extent in EPSG:3395 metres, as autk-db's workspace holds it:
// Niterói's summer surface temperature, read as 4 columns by 3 rows.
const BBOX = [-4802000, -2604000, -4780000, -2589000];
// Two of its bands, rows from south to north, as autk-db reads every band:
// one value a cell, each exact in float32.
const BAND_1 = [27.5, 28.25, 29, 29.75, 30.5, 31.25, 32, 32.75, 33.5, 34.25, 35, 35.75];
const BAND_2 = [26.75, 27.25, 27.75, 28.25, 28.75, 29.25, 29.75, 30.25, 30.75, 31.25, 31.75, 32.25];

// The outline of the raster's extent, a layer the document loads before it,
// as the grammar's gallery draws one under its GeoTIFF.
const EXTENT = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: [[[-4802000, -2604000], [-4780000, -2604000], [-4780000, -2589000], [-4802000, -2589000], [-4802000, -2604000]]],
    },
    properties: {},
  }],
};

/** What the grammar's adapter was asked to load, what autk-db's loadGeoTiff was called with, and the workspace of each. */
const mockResolved: Array<{ db: any; source: any }> = [];
const mockLoaded: any[] = [];
const mockLoadedIn: string[] = [];
/** Whether loadGeoTiff fails, as autk-db's does for a file the server does not have. */
let mockFileMissing = false;

const mockCreateDataAdapter = jest.fn((...args: any[]) => {
  // Every other source as the grammar's own adapter loads it.
  const grammar = jest.requireActual("@urban-toolkit/autk-grammar/data").createDataAdapter(...args);
  return {
    // As autk-grammar 5's adapter loads a geotiff source: autk-db's loadGeoTiff,
    // with every key of the source but its type and its workspace, in its workspace.
    resolveSource: jest.fn(async (db: any, source: any) => {
      mockResolved.push({ db, source });
      if (source.type !== "geotiff") return grammar.resolveSource(db, source);
      const { type: _type, workspace, ...params } = source;
      await jest.requireActual("@urban-toolkit/autk-grammar/data").enterWorkspace(db, workspace);
      await db.loadGeoTiff(params);
      return db;
    }),
  };
});

class mockAutkDb {
  /** The workspace the database works in; autk-db finds a table in it alone. */
  workspace = "autk";
  /** Each workspace's tables, and the rasters, by workspace and table. */
  layers = new Map<string, string[]>();
  rasters = new Set<string>();
  init() { return Promise.resolve(); }
  getCurrentWorkspace() { return this.workspace; }
  setWorkspace(name: string) { this.workspace = name; return Promise.resolve(); }
  loadGeojson(params: any) {
    this.layers.set(this.workspace, [...(this.layers.get(this.workspace) ?? []), params.outputTableName]);
    return Promise.resolve();
  }
  getLayersMetadata() {
    return (this.layers.get(this.workspace) ?? []).map((name) => ({ name, type: "polygons", source: "geojson", columns: [] }));
  }
  getLayer() { return Promise.resolve(JSON.parse(JSON.stringify(EXTENT))); }
  getWorkspaceConfiguration() { return { coordinateFormat: "EPSG:3395", precisionGrid: 0.01 }; }
  loadGeoTiff(params: any) {
    if (mockFileMissing) {
      return Promise.reject(new Error(`Failed to fetch GeoTIFF from ${params.geotiffFileUrl}: HTTP 404`));
    }
    mockLoaded.push(params);
    mockLoadedIn.push(this.workspace);
    this.rasters.add(`${this.workspace}.${params.outputTableName}`);
    return Promise.resolve({ source: "geotiff", type: "raster", name: params.outputTableName });
  }
  // As autk-db 4.1.1's getRaster gives a GeoTIFF table of the current
  // workspace: its bands labelled by their ids, at the extent its corners take
  // in the workspace's CRS.
  getRaster(name: string) {
    if (!this.rasters.has(`${this.workspace}.${name}`)) {
      return Promise.reject(new Error(`Table ${name} is not a compact raster table.`));
    }
    return Promise.resolve({
      type: "FeatureCollection",
      bbox: [...BBOX],
      features: [{
        type: "Feature",
        geometry: null,
        properties: {
          rasterResX: 4,
          rasterResY: 3,
          bands: [{ id: "band_1", label: "band_1" }, { id: "band_2", label: "band_2" }],
          originalRasterResX: 22,
          originalRasterResY: 15,
          band_1: Float32Array.from(BAND_1),
          band_2: Float32Array.from(BAND_2),
        },
      }],
    });
  }
}

// A file of the repository, as the grammar's gallery loads it: its first image
// in the CRS the file is in, at most 200 cells, each the value of a cell of
// the file.
const FILE = "docs/examples/data/niteroi_lst_verao_2001_2024.tif";
const GEOTIFF = {
  type: "geotiff",
  geotiffFileUrl: FILE,
  outputTableName: "lst",
  coordinateFormat: "EPSG:4326",
  maxRasterCells: 200,
  resampleMethod: "nearest",
};
const SOURCES = [
  { type: "geojson", outputTableName: "extent", geojsonObject: EXTENT, coordinateFormat: "EPSG:3395" },
  GEOTIFF,
];

/** Where the browser reaches the backend, in these tests. */
const BACKEND = "http://backend.test:5002";

/** The grid the raster's cells lie on, over its extent, north up. */
const GRID = { crs: "EPSG:3395", width: 4, height: 3, originX: -4802000, originY: -2589000, resX: 5500, resY: -5000 };

const IMPORT_AUTK_DB = "import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';";
const IMPORT_GRAMMAR_DATA = "import { createDataAdapter } from '@urban-toolkit/autk-grammar/data';";

/** The grammar data entry's own `enterWorkspace` and `tableKey`, which the sandbox's code imports. */
const { enterWorkspace, tableKey } = jest.requireActual("@urban-toolkit/autk-grammar/data");

/** The document's sources with their file URLs resolved, as the node resolves them for the sandbox. */
function forTheSandbox(sources: any[]): any[] {
  return resolveDataSourceUrls({ data: sources }, SANDBOX_BACKEND_URL_TOKEN).data;
}

/** The document's sources with their file URLs resolved, as the node resolves them for the browser. */
function forTheBrowser(sources: any[]): any[] {
  return resolveDataSourceUrls({ data: sources }, BACKEND).data;
}

/** What the sandbox's code returns, run as the sandbox runs it. */
async function sandboxLoad(sources: any[]): Promise<any[]> {
  const body = compileDataSpecToAutkDbJs(forTheSandbox(sources)).replace(/^import [^\n]*\n/gm, "");
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
  mockLoaded.length = 0;
  mockLoadedIn.length = 0;
  mockFileMissing = false;
  mockCreateDataAdapter.mockClear();
});

describe("the sandbox's loader", () => {
  test("imports the grammar's ./data entry, after autk-db, for a document with a GeoTIFF", () => {
    const code = compileDataSpecToAutkDbJs(forTheSandbox(SOURCES));
    expect(code.match(/^import [^\n]*$/gm)).toEqual([IMPORT_AUTK_DB, IMPORT_GRAMMAR_DATA]);
  });

  test("loads a file of the repository through the grammar's data adapter, fetched from the backend the sandbox reaches", async () => {
    await sandboxLoad(SOURCES);
    expect(mockCreateDataAdapter).toHaveBeenCalledTimes(1);
    const url = `${SANDBOX_BACKEND_URL_TOKEN}/file/${FILE}`;
    // The extent's layer, then the GeoTIFF, in one database.
    expect(mockResolved.map(({ source }) => source)).toEqual([SOURCES[0], { ...GEOTIFF, geotiffFileUrl: url }]);
    expect(mockResolved[0].db).toBeInstanceOf(mockAutkDb);
    expect(mockResolved[1].db).toBe(mockResolved[0].db);
    // autk-db is handed the source's own keys: the file's CRS, the most cells
    // it decodes and how it shrinks a larger raster.
    expect(mockLoaded).toEqual([{
      geotiffFileUrl: url, outputTableName: "lst", coordinateFormat: "EPSG:4326",
      maxRasterCells: 200, resampleMethod: "nearest",
    }]);
  });

  test("loads a GeoTIFF at a URL from that URL", async () => {
    const url = "https://data.example.org/lst/niteroi.tif";
    await sandboxLoad([{ ...GEOTIFF, geotiffFileUrl: url }]);
    expect(mockLoaded.map((params) => params.geotiffFileUrl)).toEqual([url]);
  });

  test("hands the GeoTIFF on after the layers, as a raster in its envelope, on the grid its cells lie on", async () => {
    const out = await sandboxLoad(SOURCES);
    expect(out.map((table: any) => table.name ?? table.layerName)).toEqual(["extent", "lst"]);
    const [, lst] = out;
    expect(lst.dataType).toBe("raster");
    const collection = collectionIn(lst);
    expect(collection.grid).toEqual(GRID);
    expect(collection.bbox).toEqual(BBOX);
    const properties = collection.features[0].properties;
    expect(properties.bands).toEqual([{ id: "band_1", label: "band_1" }, { id: "band_2", label: "band_2" }]);
    expect(Array.from(properties.band_1 as Float32Array)).toEqual(BAND_1);
    expect(Array.from(properties.band_2 as Float32Array)).toEqual(BAND_2);
  });

  test("a GeoTIFF that does not load fails the load, naming it and why", async () => {
    mockFileMissing = true;
    const missing = { ...GEOTIFF, geotiffFileUrl: "docs/examples/data/no_such_raster.tif" };
    await expect(sandboxLoad([SOURCES[0], missing])).rejects.toThrow(
      "autk data load produced 1 fewer table(s) than the spec asked for - missing: lst"
      + ` (geotiff: Failed to fetch GeoTIFF from ${SANDBOX_BACKEND_URL_TOKEN}/file/docs/examples/data/no_such_raster.tif: HTTP 404)`,
    );
  });
});

describe("the in-browser loader", () => {
  test("loads a file of the repository through the data entry's data adapter, fetched from the backend", async () => {
    await loadSpecLayers({ data: forTheBrowser(SOURCES) });
    expect(mockCreateDataAdapter).toHaveBeenCalledTimes(1);
    // The extent's layer, then the GeoTIFF, in one database.
    expect(mockResolved.map(({ source }) => source)).toEqual([
      SOURCES[0], { ...GEOTIFF, geotiffFileUrl: `${BACKEND}/file/${FILE}` },
    ]);
    expect(mockResolved[0].db).toBeInstanceOf(mockAutkDb);
    expect(mockResolved[1].db).toBe(mockResolved[0].db);
    expect(mockLoaded.map((params) => [params.outputTableName, params.geotiffFileUrl])).toEqual([
      ["lst", `${BACKEND}/file/${FILE}`],
    ]);
  });

  test("reads the GeoTIFF back after the layers, as a raster with the grid its cells lie on", async () => {
    const tables: any[] = await loadSpecLayers({ data: forTheBrowser(SOURCES) });
    expect(tables.map((table) => [table.name, table.type])).toEqual([["extent", "polygons"], ["lst", "raster"]]);
    const lst = tables[1].geojson;
    expect(lst.grid).toEqual(GRID);
    expect(lst.features[0].properties.bands).toEqual([{ id: "band_1", label: "band_1" }, { id: "band_2", label: "band_2" }]);
    expect(Array.from(lst.features[0].properties.band_2)).toEqual(BAND_2);
  });

  test("hands the GeoTIFF on after the layers, as a raster in its envelope", async () => {
    const out = await toPoolOutput(await loadSpecLayers({ data: forTheBrowser(SOURCES) }), undefined, "lst-node");
    expect(out.dataType).toBe("outputs");
    expect(out.data.map((item: any) => [item.dataType, item.layerName])).toEqual([
      ["geodataframe", "extent"],
      ["raster", "lst"],
    ]);
    const collection = collectionIn(out.data[1]);
    expect(collection.grid).toEqual(GRID);
    expect(Array.from(collection.features[0].properties.band_1 as Float32Array)).toEqual(BAND_1);
  });

  test("a GeoTIFF that does not load fails the load, naming it and why", async () => {
    mockFileMissing = true;
    const missing = { ...GEOTIFF, geotiffFileUrl: "docs/examples/data/no_such_raster.tif" };
    await expect(loadSpecLayers({ data: forTheBrowser([SOURCES[0], missing]) })).rejects.toThrow(
      "autk data load produced 1 fewer table(s) than the spec asked for - missing: lst"
      + ` (geotiff: Failed to fetch GeoTIFF from ${BACKEND}/file/docs/examples/data/no_such_raster.tif: HTTP 404)`,
    );
  });
});

test("both loaders hand the GeoTIFF on in the same envelope", async () => {
  const [, fromSandbox] = await sandboxLoad(SOURCES);
  const fromBrowser = (await toPoolOutput(await loadSpecLayers({ data: forTheBrowser(SOURCES) }), undefined, "lst-node")).data[1];
  expect(fromSandbox).toEqual(fromBrowser);
});

// A GeoTIFF in a workspace (autk-grammar 5.0.0's `workspace`) is loaded there
// and handed on with it, as a table is and as a heatmap is. Its data section
// imports all it needs of the grammar's data entry in one line.
describe("a GeoTIFF in a workspace", () => {
  const IN_EAST = [{ ...SOURCES[0], workspace: "east" }, { ...GEOTIFF, workspace: "east" }];

  test("the sandbox's code imports the data adapter and the workspace functions in one line", () => {
    expect(compileDataSpecToAutkDbJs(forTheSandbox(IN_EAST)).match(/^import [^\n]*$/gm)).toEqual([
      IMPORT_AUTK_DB,
      "import { createDataAdapter, enterWorkspace, tableKey } from '@urban-toolkit/autk-grammar/data';",
    ]);
  });

  test("both loaders load it in its workspace and hand it on with it, after its layer", async () => {
    const fromSandbox = await sandboxLoad(IN_EAST);
    expect(fromSandbox.map((item: any) => [item.name ?? item.layerName, item.workspace])).toEqual([
      ["extent", "east"], ["lst", "east"],
    ]);
    const tables: any[] = await loadSpecLayers({ data: forTheBrowser(IN_EAST) });
    expect(tables.map((table) => [table.name, table.type, table.workspace])).toEqual([
      ["extent", "polygons", "east"], ["lst", "raster", "east"],
    ]);
    expect(mockLoadedIn).toEqual(["east", "east"]);

    const fromBrowser = (await toPoolOutput(tables, undefined, "lst-node")).data[1];
    expect(fromBrowser.workspace).toBe("east");
    expect(fromSandbox[1]).toEqual(fromBrowser);
    expect(collectionIn(fromBrowser).grid).toEqual(GRID);
  });
});
