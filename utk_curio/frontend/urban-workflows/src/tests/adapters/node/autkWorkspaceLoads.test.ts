/**
 * Both loaders of an Autark node's data section load each source into its
 * `workspace` (autk-grammar 5.0.0), and every table they hand on keeps it.
 *
 * The sandbox's loader is the JavaScript `compileDataSpecToAutkDbJs` writes,
 * run here as the sandbox runs it: its imports dropped, autk-db's stood in and
 * autk-grammar's data entry's own `enterWorkspace` and `tableKey` handed in.
 * The browser's loader is `loadSpecLayers`, which imports that same entry.
 * autk-db is a stand-in that keeps a table in the workspace it was loaded
 * into, as autk-db does: it finds a table by its name in the current workspace
 * only, and a table loaded under a name the workspace holds replaces it.
 */
jest.mock("../../../services/api", () => ({ fetchData: (...a: any[]) => mockFetchData(...a) }));
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_NAME: "autk",
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  AutkDb: function AutkDb() { return new mockWorkspacesDb(); },
}), { virtual: true });

const mockFetchData = jest.fn();

/** Every load the stand-in took: the table and the workspace it went into. */
const mockLoads: Array<{ table: string; workspace: string }> = [];

/** autk-db's workspaces, as far as a loader sees them. */
class mockWorkspacesDb {
  private workspace = "autk";
  private tables = new Map<string, Map<string, any>>();
  async init() {}
  getCurrentWorkspace() { return this.workspace; }
  async setWorkspace(name: string) { this.workspace = name; }
  private current(): Map<string, any> {
    if (!this.tables.has(this.workspace)) this.tables.set(this.workspace, new Map());
    return this.tables.get(this.workspace)!;
  }
  async loadGeojson({ outputTableName, geojsonObject }: any) {
    mockLoads.push({ table: outputTableName, workspace: this.workspace });
    this.current().set(outputTableName, geojsonObject);
  }
  getLayersMetadata() {
    return [...this.current().keys()].map((name) => ({ name, type: "polylines", source: "geojson" }));
  }
  async getLayer(name: string) {
    const table = this.current().get(name);
    if (!table) throw new Error(`Table ${name} not found.`);
    return JSON.parse(JSON.stringify(table));
  }
  /** A join of two tables of the current workspace, which writes nothing here. */
  async spatialQuery({ tableRootName, tableJoinName }: any) {
    for (const name of [tableRootName, tableJoinName]) {
      if (!this.current().has(name)) throw new Error(`Table ${name} not found.`);
    }
  }
}

import { compileDataSpecToAutkDbJs } from "../../../adapters/node/autkDataCompile";
import {
  layersToPoolWrapper,
  loadSpecLayers,
  materializeBackendLayers,
} from "../../../adapters/node/autkLayerMaterialize";
import { CURIO_RASTER_SOURCE, withRasterSources } from "../../../adapters/node/autkRasters";
import { framesFromPayload } from "../../../utils/grammarInput";

/** What the sandbox's code imports of autk-grammar's data entry, its own. */
const { enterWorkspace, tableKey } = require("@urban-toolkit/autk-grammar/data");

const line = (x: number) => ({
  type: "Feature",
  geometry: { type: "LineString", coordinates: [[x, 41.88], [x + 0.001, 41.881]] },
  properties: { x },
});
const lines = (...xs: number[]) => ({ type: "FeatureCollection", features: xs.map(line) });

/** `lines` in the default workspace and in `east`, and `points` in `autk`, the default one named. */
const SOURCES = [
  { type: "geojson", outputTableName: "lines", geojsonObject: lines(-87.6) },
  { type: "geojson", outputTableName: "lines", geojsonObject: lines(-87.5, -87.49, -87.48), workspace: "east" },
  { type: "geojson", outputTableName: "points", geojsonObject: lines(-87.61, -87.62), workspace: "autk" },
];

/** Each table handed on: its name, its workspace, and its rows' `x`. */
const handedOn = (layers: any[]) => layers.map((layer) => [
  layer.name, layer.workspace, layer.geojson.features.map((f: any) => f.properties.x),
]);

const EXPECTED = [
  ["lines", undefined, [-87.6]],
  ["points", undefined, [-87.61, -87.62]],
  ["lines", "east", [-87.5, -87.49, -87.48]],
];

async function runInSandbox(sources: any[]): Promise<any[]> {
  const body = compileDataSpecToAutkDbJs(sources).replace(/^import [^\n]*\n/gm, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  return new AsyncFunction("AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "enterWorkspace", "tableKey", body)(
    mockWorkspacesDb, "EPSG:3395", enterWorkspace, tableKey,
  );
}

beforeEach(() => {
  mockLoads.length = 0;
  mockFetchData.mockReset();
});

describe("the sandbox's loader", () => {
  test("imports autk-grammar's data entry for a data section that names a workspace, and only then", () => {
    expect(compileDataSpecToAutkDbJs(SOURCES))
      .toContain("\nimport { enterWorkspace, tableKey } from '@urban-toolkit/autk-grammar/data';\n");
    // The default workspace, named or not, is no other workspace.
    expect(compileDataSpecToAutkDbJs([SOURCES[0], SOURCES[2]])).not.toContain("@urban-toolkit/autk-grammar/data");
  });

  test("loads each source into its workspace", async () => {
    await runInSandbox(SOURCES);
    expect(mockLoads).toEqual([
      { table: "lines", workspace: "autk" },
      { table: "lines", workspace: "east" },
      { table: "points", workspace: "autk" },
    ]);
  });

  test("keeps two workspaces' tables of one name apart, each handed on with its workspace", async () => {
    const layers = await runInSandbox(SOURCES);
    expect(handedOn(layers)).toEqual(EXPECTED);
    // A table of the default workspace is handed on as before: no workspace written.
    expect(Object.keys(layers[0]).sort()).toEqual(["geojson", "name", "type"]);
  });

  test("joins the tables of the join's own workspace", async () => {
    // `east` holds no `lines`: the default workspace's is not east's.
    const sources = [
      { type: "geojson", outputTableName: "lines", geojsonObject: lines(-87.6) },
      { type: "join", dataRef: "lines", joinDataRef: "lines", workspace: "east" },
    ];
    await expect(runInSandbox(sources)).rejects.toThrow("spatial join failed - Table lines not found.");
    // In its own workspace it joins.
    await expect(runInSandbox([sources[0], { ...sources[1], workspace: undefined }])).resolves.toHaveLength(1);
  });
});

describe("the browser's loader", () => {
  test("loads each source into its workspace", async () => {
    await loadSpecLayers({ data: SOURCES });
    expect(mockLoads).toEqual([
      { table: "lines", workspace: "autk" },
      { table: "lines", workspace: "east" },
      { table: "points", workspace: "autk" },
    ]);
  });

  test("joins the tables of the join's own workspace", async () => {
    const sources = [
      { type: "geojson", outputTableName: "lines", geojsonObject: lines(-87.6) },
      { type: "join", dataRef: "lines", joinDataRef: "lines", workspace: "east" },
    ];
    await expect(loadSpecLayers({ data: sources })).rejects.toThrow("spatial join failed - Table lines not found.");
  });

  test("keeps two workspaces' tables of one name apart, each handed on with its workspace", async () => {
    expect(handedOn(await loadSpecLayers({ data: SOURCES }))).toEqual(EXPECTED);
  });
});

describe("a raster a map draws", () => {
  test("loads into its workspace, and each workspace's raster of one name is served there", async () => {
    const loaded: Array<[string, string]> = [];
    const db: any = {
      workspace: "autk",
      getCurrentWorkspace() { return this.workspace; },
      async setWorkspace(name: string) { this.workspace = name; },
      async loadGeoTiff({ outputTableName }: any) { loaded.push([outputTableName, this.workspace]); },
      // autk-db reads a raster of the current workspace.
      async getRaster() {
        return { type: "FeatureCollection", bbox: [0, 0, 1, 1], features: [{ type: "Feature", geometry: null, properties: { from: this.workspace } }] };
      },
      async getLayer(name: string) { throw new Error(`Table ${name} not found.`); },
    };
    const grammar: any = { dataAdapter: { resolveSource: async (given: any) => given } };
    withRasterSources(grammar, async () => db, enterWorkspace);
    const raster = (workspace?: string) => ({
      type: CURIO_RASTER_SOURCE,
      outputTableName: "input_0",
      geotiffArrayBuffer: new ArrayBuffer(8),
      load: { coordinateFormat: "EPSG:3395", maxRasterCells: 1, resampleMethod: "nearest" },
      grid: {},
      cells: 1,
      ...(workspace ? { workspace } : {}),
    });
    await grammar.dataAdapter.resolveSource(db, raster("east"));
    // The default one is entered too: the source before left the database in east.
    await grammar.dataAdapter.resolveSource(db, raster());
    expect(loaded).toEqual([["input_0", "east"], ["input_0", "autk"]]);
    // A map reads a raster in its own workspace.
    await enterWorkspace(db, "east");
    expect((await db.getRaster("input_0")).features[0].properties.from).toBe("east");
    expect((await db.getLayer("input_0")).features[0].properties.from).toBe("east");
    await enterWorkspace(db);
    expect((await db.getRaster("input_0")).features[0].properties.from).toBe("autk");
  });
});

describe("what a node hands on keeps each table's workspace", () => {
  const LAYERS = [
    { name: "lines", type: "polylines", geojson: lines(-87.6) },
    { name: "lines", type: "polylines", geojson: lines(-87.5), workspace: "east" },
  ];

  test("in the wrapper a compute step or the browser's loader hands on", () => {
    const wrapper = layersToPoolWrapper(LAYERS);
    expect(wrapper.data.map((envelope: any) => [envelope.layerName, envelope.workspace])).toEqual([
      ["lines", undefined],
      ["lines", "east"],
    ]);
    expect(Object.keys(wrapper.data[0]).sort()).toEqual(["data", "dataType", "layerName", "layerType"]);
    expect(layersToPoolWrapper([LAYERS[1]]).workspace).toBe("east");
  });

  test("in the frames a node reads from a layer array and from a wrapper", () => {
    const records = LAYERS.map(({ name, type, geojson, workspace }: any) => ({ name, type, geojson, ...(workspace ? { workspace } : {}) }));
    expect(framesFromPayload(records).frames.map((frame) => [frame.name, frame.workspace])).toEqual([
      ["lines", undefined],
      ["lines", "east"],
    ]);
    expect(framesFromPayload(layersToPoolWrapper(LAYERS)).frames.map((frame) => [frame.name, frame.workspace])).toEqual([
      ["lines", undefined],
      ["lines", "east"],
    ]);
  });

  test("in the layers a map draws from its own data section's load", async () => {
    mockFetchData.mockResolvedValue({
      dataType: "list",
      data: LAYERS.map(({ name, type, geojson, workspace }: any) => ({ name, type, geojson, ...(workspace ? { workspace } : {}) })),
    });
    const layers = await materializeBackendLayers(null, { path: "art-1", dataType: "list" });
    expect(layers.map((layer) => [layer.name, layer.workspace])).toEqual([
      ["lines", undefined],
      ["lines", "east"],
    ]);
  });
});
