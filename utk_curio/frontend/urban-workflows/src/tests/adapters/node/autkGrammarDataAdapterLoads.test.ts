/**
 * Both loaders of an Autark node's data section load it as autk-grammar's run
 * loads one: through the grammar's own data adapter (`createDataAdapter`, from
 * its `./data` entry), the document's `workspaces` first (`resolveWorkspaces`),
 * then each source in order (`resolveSource`), every type alike: an
 * OpenStreetMap area, CSV, JSON and GeoJSON tables, a join, a SQL table, an
 * update and a drop. So a source the grammar refuses fails a node's load in
 * the grammar's words, and what each loads is what the grammar's adapter
 * hands autk-db.
 *
 * The sandbox's loader is the JavaScript `compileDataSpecToAutkDbJs` writes,
 * run here as the sandbox runs it: its imports dropped, autk-db's stood in and
 * the data entry's own exports handed in. The browser's loader is
 * `loadSpecLayers`, which imports that same entry. The data adapter is the
 * entry's own, recording each call; autk-db is a stand-in that keeps each
 * workspace's tables, of the types autk-db gives them, and answers what the
 * adapter asks of it.
 *
 * What they hand on:
 * - the tables a section asks for (requestedLayerTables): an OpenStreetMap
 *   area's layers and tag sets, a SQL table, and no table a later `drop`
 *   drops;
 * - a SQL table without a layer type, and a CSV table an `update` changed, as
 *   their rows;
 * - each table in the CRS of its workspace, which `workspaces` sets;
 * - an OpenStreetMap table a view of the node reads with `osmElements`, read
 *   as one feature per OpenStreetMap element (`getLayer(name, {osmElements})`).
 */
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_NAME: "autk",
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  AutkDb: function AutkDb() { return new mockDatabase(); },
  isVectorTable: (table: any) => ["points", "polylines", "polygons", "roads", "buildings", "parks", "water", "surface"]
    .includes(table?.type),
  isRenderableTable: (table: any) => table?.type !== undefined,
}), { virtual: true });
// The grammar's own data adapter, recording each call it is handed. Plain, as
// every suite mocks this entry (mockKinds.test.ts).
jest.mock("@urban-toolkit/autk-grammar/data", () => {
  const actual = jest.requireActual("@urban-toolkit/autk-grammar/data");
  return {
    ...actual,
    createDataAdapter: (...args: unknown[]) => {
      const adapter = actual.createDataAdapter(...args);
      return {
        resolveWorkspaces: (db: unknown, workspaces: unknown[]) => {
          mockAdapterCalls.push(["workspaces", workspaces]);
          return adapter.resolveWorkspaces(db, workspaces);
        },
        resolveSource: (db: unknown, source: any) => {
          mockAdapterCalls.push(["source", source?.type, source?.outputTableName ?? source?.dataRef]);
          return adapter.resolveSource(db, source);
        },
      };
    },
  };
});

/** Each call the grammar's data adapter was handed, in order. */
const mockAdapterCalls: unknown[][] = [];
/** Each read of a table's rows: its name and the options autk-db was handed. */
const mockReads: Array<{ table: string; options: unknown }> = [];

type Table = { type?: string; source?: string; rows: any[] };

/** autk-db, as far as the grammar's data adapter and the loaders ask it. */
class mockDatabase {
  private workspace = "autk";
  private configurations = new Map<string, { coordinateFormat: string; precisionGrid: number }>();
  private tables = new Map<string, Map<string, Table>>();
  async init() {}
  getCurrentWorkspace() { return this.workspace; }
  async setWorkspace(name: string, configuration?: { coordinateFormat: string; precisionGrid: number }) {
    if (configuration) this.configurations.set(name, configuration);
    this.workspace = name;
  }
  getWorkspaceConfiguration() {
    return this.configurations.get(this.workspace) ?? { coordinateFormat: "EPSG:3395", precisionGrid: 0.01 };
  }
  private current(): Map<string, Table> {
    if (!this.tables.has(this.workspace)) this.tables.set(this.workspace, new Map());
    return this.tables.get(this.workspace)!;
  }
  /** A layer's features, its coordinates as this workspace keeps them: here, as they came. */
  async loadGeojson({ outputTableName, geojsonObject, layerType }: any) {
    const first = geojsonObject.features.find((f: any) => f?.geometry)?.geometry?.type ?? "";
    const type = layerType ?? (/Point/.test(first) ? "points" : /LineString/.test(first) ? "polylines" : "polygons");
    this.current().set(outputTableName, { type, source: "geojson", rows: geojsonObject.features });
  }
  async loadCsv({ outputTableName, csvObject }: any) {
    const [header, ...rows] = csvObject;
    this.current().set(outputTableName, {
      source: "csv", rows: rows.map((row: any[]) => Object.fromEntries(header.map((key: string, i: number) => [key, row[i]]))),
    });
  }
  async loadJson({ outputTableName, jsonObject }: any) {
    this.current().set(outputTableName, { source: "json", rows: jsonObject });
  }
  /** An area's layers, each with one OpenStreetMap feature. */
  async loadOsm({ outputTableName, autoLoadLayers }: any) {
    for (const layer of autoLoadLayers?.layers ?? []) {
      this.current().set(`${outputTableName}_${layer}`, {
        type: layer, source: "osm",
        rows: [{ type: "Feature", id: 7, properties: { highway: "primary" }, geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] } }],
      });
    }
  }
  async spatialQuery({ tableRootName, tableJoinName }: any) {
    for (const name of [tableRootName, tableJoinName]) {
      if (!this.current().has(name)) throw new Error(`Table ${name} not found.`);
    }
  }
  /** A query's table, of the type its output names: here, the zones of the two spots, as text. */
  async rawQuery({ output }: any) {
    this.current().set(output.tableName, { type: output.tableType, source: output.source, rows: [{ zone: "1" }, { zone: "2" }] });
  }
  async updateTable({ tableName, data, strategy, idColumn }: any) {
    const table = this.current().get(tableName);
    if (!table) throw new Error(`Table ${tableName} not found.`);
    if (strategy === "replace") {
      table.rows = [...data];
      return;
    }
    for (const row of data) {
      const at = table.rows.findIndex((held) => held[idColumn] === row[idColumn]);
      if (at < 0) table.rows.push(row);
      else table.rows[at] = row;
    }
  }
  async removeLayer(name: string) { this.current().delete(name); }
  getTablesMetadata() {
    return [...this.current()].map(([name, { type, source }]) => ({ name, type, source, columns: [] }));
  }
  getLayersMetadata() { return this.getTablesMetadata().filter((table) => table.type !== undefined); }
  async getLayer(name: string, options?: unknown) {
    const table = this.current().get(name);
    if (!table || table.type === undefined) throw new Error(`Table ${name} not found.`);
    mockReads.push({ table: name, options });
    return JSON.parse(JSON.stringify({ type: "FeatureCollection", features: table.rows }));
  }
  async getTable(name: string) {
    const table = this.current().get(name);
    if (!table) throw new Error(`Table ${name} not found.`);
    return JSON.parse(JSON.stringify(table.rows));
  }
}

import {
  compileDataSpecToAutkDbJs,
  requestedLayerTables,
} from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";

/** What the sandbox's code imports of autk-grammar's data entry: its own, the adapter recording. */
const dataEntry = require("@urban-toolkit/autk-grammar/data");

/** A point of the Loop, in degrees, with its zone. */
const spot = (x: number, zone: number) => ({
  type: "Feature", properties: { zone }, geometry: { type: "Point", coordinates: [x, 41.88] },
});

/** One source of every type a section loads, in the order a section loads them. */
const EVERY_TYPE = [
  {
    type: "osm", outputTableName: "loop", pbfFileUrl: "loop.osm.pbf", queryArea: { bbox: [-87.64, 41.87, -87.62, 41.89] },
    autoLoadLayers: { layers: ["roads"], coordinateFormat: "EPSG:4326" },
  },
  { type: "geojson", outputTableName: "spots", coordinateFormat: "EPSG:4326", geojsonObject: { type: "FeatureCollection", features: [spot(-87.63, 1), spot(-87.62, 2)] } },
  { type: "csv", outputTableName: "sales", csvObject: [["month", "total"], ["Jan", 3], ["Feb", 5]] },
  { type: "json", outputTableName: "notes", jsonObject: [{ note: "kept" }] },
  { type: "join", dataRef: "spots", joinDataRef: "spots" },
  { type: "sql", outputTableName: "zone_names", query: "SELECT properties->>'zone' AS zone FROM spots" },
  { type: "update", dataRef: "sales", strategy: "update", idColumn: "month", jsonObject: [{ month: "Feb", total: 9 }] },
  { type: "drop", dataRef: "notes" },
];

/** What the adapter is handed for EVERY_TYPE, in order. */
const EVERY_TYPE_CALLS = [
  ["source", "osm", "loop"],
  ["source", "geojson", "spots"],
  ["source", "csv", "sales"],
  ["source", "json", "notes"],
  ["source", "join", "spots"],
  ["source", "sql", "zone_names"],
  ["source", "update", "sales"],
  ["source", "drop", "notes"],
];

/** The default workspace in Web Mercator to the metre. */
const WEB_MERCATOR = [{ coordinateFormat: "EPSG:3857", precisionGrid: 1 }];

/** The sandbox's code, run as the sandbox runs it: its imports dropped, theirs handed in. */
async function runInSandbox(sources: any[], options?: Record<string, unknown>): Promise<any[]> {
  const body = (compileDataSpecToAutkDbJs as any)(sources, options).replace(/^import [^\n]*\n/gm, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  return new AsyncFunction(
    "AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "createDataAdapter", "enterWorkspace", "tableKey", body,
  )(mockDatabase, "EPSG:3395", dataEntry.createDataAdapter, dataEntry.enterWorkspace, dataEntry.tableKey);
}

/** The browser's loader. */
const loadInBrowser = (spec: any, options?: Record<string, unknown>) => (loadSpecLayers as any)(spec, [], options);

/** Each table handed on: its name, its type, and its rows. */
const handedOn = (layers: any[]) => Object.fromEntries(layers.map((layer) => [layer.name, layer]));

const loaders: Array<[string, (spec: any, options?: Record<string, unknown>) => Promise<any[]>]> = [
  ["the sandbox's loader", (spec, options) => runInSandbox(spec.data, { workspaces: spec.workspaces, ...options })],
  ["the browser's loader", loadInBrowser],
];

beforeEach(() => {
  mockAdapterCalls.length = 0;
  mockReads.length = 0;
});

describe.each(loaders)("%s", (_name, load) => {
  test("hands every source to the grammar's data adapter, in order", async () => {
    await load({ data: EVERY_TYPE });
    expect(mockAdapterCalls).toEqual(EVERY_TYPE_CALLS);
  });

  test("sets the document's workspaces up through the grammar's data adapter before the first source", async () => {
    await load({ workspaces: WEB_MERCATOR, data: [EVERY_TYPE[1]] });
    expect(mockAdapterCalls).toEqual([["workspaces", WEB_MERCATOR], ["source", "geojson", "spots"]]);
  });

  test("hands on each table of a workspace in the CRS workspaces sets", async () => {
    const layers = handedOn(await load({ workspaces: WEB_MERCATOR, data: [EVERY_TYPE[1]] }));
    // The stand-in keeps the coordinates as they came, in degrees, and the
    // load says in which CRS: a table in metres would say EPSG:3857.
    expect(layers.spots.geojson.crs?.properties?.name).toBe("urn:ogc:def:crs:EPSG::4326");
    const metres = handedOn(await load({
      workspaces: WEB_MERCATOR,
      data: [{ ...EVERY_TYPE[1], coordinateFormat: "EPSG:3857", geojsonObject: { type: "FeatureCollection", features: [{
        type: "Feature", properties: { zone: 1 }, geometry: { type: "Point", coordinates: [-9754927, 5143021] },
      }] } }],
    }));
    expect(metres.spots.geojson.crs?.properties?.name).toBe("urn:ogc:def:crs:EPSG::3857");
  });

  test("fails in the grammar's words on tag sets with an extract, and loads nothing of it", async () => {
    const source = {
      type: "osm", outputTableName: "tip", pbfFileUrl: "tip.osm.pbf", queryArea: { bbox: [-74.0194, 40.7, -74.0085, 40.7085] },
      tagSets: [{ name: "cafes", type: "points", tags: [{ key: "amenity", value: "cafe" }] }],
    };
    await expect(load({ data: [source] })).rejects.toThrow(
      'OSM source "tip": tagSets are read from the Overpass API only, so a source with pbfFileUrl cannot take them.',
    );
  });

  test("hands on a SQL table without a layer type and an updated CSV table as their rows, and no dropped table", async () => {
    const layers = handedOn(await load({ data: EVERY_TYPE }));
    expect(Object.keys(layers).sort()).toEqual(["loop_roads", "sales", "spots", "zone_names"]);
    expect(layers.zone_names.geojson.features.map((f: any) => [f.geometry, f.properties])).toEqual([
      [null, { zone: "1" }], [null, { zone: "2" }],
    ]);
    expect(layers.sales.geojson.features.map((f: any) => f.properties)).toEqual([
      { month: "Jan", total: 3 }, { month: "Feb", total: 9 },
    ]);
  });

  test("reads a table a view reads with osmElements as one feature per OpenStreetMap element, and no other", async () => {
    await load({ data: [EVERY_TYPE[0], EVERY_TYPE[1]] }, { elements: ["loop_roads"] });
    expect(mockReads.filter((read) => read.table === "loop_roads").map((read) => read.options)).toEqual([{ osmElements: true }]);
    expect(mockReads.filter((read) => read.table === "spots").map((read) => read.options ?? null)).toEqual([null]);
  });
});

describe("the tables a data section asks for", () => {
  test("are an area's layers and tag sets, a SQL table, and no table a later drop drops", () => {
    expect(requestedLayerTables([
      {
        type: "osm", outputTableName: "box", queryArea: { bbox: [-74.0125, 40.705, -74.008, 40.7085] },
        autoLoadLayers: { layers: ["roads"] },
        tagSets: [{ name: "cafes", type: "points", tags: [{ key: "amenity" }] }, { name: "parks", type: "polygons", tags: [{ key: "leisure" }] }],
      },
      { type: "geojson", outputTableName: "scratch", geojsonObject: { type: "FeatureCollection", features: [] } },
      { type: "sql", outputTableName: "busy", query: "SELECT 1", layerType: "polygons" },
      { type: "drop", dataRef: "scratch" },
      { type: "drop", dataRef: "box_parks_polygons" },
      { type: "sql", outputTableName: "scratch", query: "SELECT 2" },
    ])).toEqual(["box_roads", "box_cafes_points", "busy", "scratch"]);
  });
});
