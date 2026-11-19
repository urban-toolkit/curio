/**
 * Both loaders of an Autark node's data section hand on a table that a CSV or
 * JSON source of the section made with no geometry (loaded without geometry
 * columns). autk-db lists such a table as no layer, so both read it back as
 * its rows, each a feature with no geometry and the row as its properties, as
 * autk-grammar reads such a table for a plot, under its name and with no layer
 * type, in its workspace (autkDataCompile's plainTableRecord). A CSV loaded
 * with geometry columns is a layer, read with the layers.
 *
 * The sandbox's loader is the JavaScript `compileDataSpecToAutkDbJs` writes,
 * run here as the sandbox runs it: its imports dropped, autk-db's stood in and
 * autk-grammar's data entry's own `createDataAdapter`, `enterWorkspace` and
 * `tableKey` handed in.
 * The browser's loader is `loadSpecLayers`. autk-db is a stand-in that keeps
 * each table in the workspace it was loaded into, a CSV or JSON table a layer
 * of points when its source names geometry columns and a table with no layer
 * type otherwise, as autk-db does.
 */
jest.mock("../../../services/api", () => ({ fetchData: (...a: any[]) => mockFetchData(...a) }));
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_NAME: "autk",
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  AutkDb: function AutkDb() { return new mockPlainTablesDb(); },
}), { virtual: true });

const mockFetchData = jest.fn();

type MockTable = { source: string; type?: string; rows: Array<Record<string, unknown>> };

/** autk-db's CSV and JSON tables, each in its workspace, as far as a loader sees them. */
class mockPlainTablesDb {
  private workspace = "autk";
  private tables = new Map<string, Map<string, MockTable>>();
  async init() {}
  getCurrentWorkspace() { return this.workspace; }
  async setWorkspace(name: string) { this.workspace = name; }
  private current(): Map<string, MockTable> {
    if (!this.tables.has(this.workspace)) this.tables.set(this.workspace, new Map());
    return this.tables.get(this.workspace)!;
  }
  private load(source: string, { outputTableName, csvObject, jsonObject, geometryColumns }: any) {
    const rows = csvObject
      ? csvObject.slice(1).map((row: unknown[]) => Object.fromEntries(csvObject[0].map((key: string, i: number) => [key, row[i]])))
      : jsonObject;
    this.current().set(outputTableName, { source, rows, ...(geometryColumns ? { type: "points" } : {}) });
  }
  async loadCsv(params: any) { this.load("csv", params); }
  async loadJson(params: any) { this.load("json", params); }
  getTablesMetadata() {
    return [...this.current()].map(([name, table]) => ({ name, source: table.source, ...(table.type ? { type: table.type } : {}) }));
  }
  getLayersMetadata() {
    return this.getTablesMetadata().filter((table) => table.type !== undefined);
  }
  async getTable(name: string) {
    const table = this.current().get(name);
    if (!table) throw new Error(`Table ${name} not found.`);
    return table.rows.map((row) => ({ ...row }));
  }
  async getLayer(name: string) {
    const table = this.current().get(name);
    if (!table?.type) throw new Error(`Table ${name} is no layer.`);
    return {
      type: "FeatureCollection",
      features: table.rows.map((row: any) => ({ type: "Feature", geometry: { type: "Point", coordinates: [row.lon, row.lat] }, properties: { ...row } })),
    };
  }
}

import { compileDataSpecToAutkDbJs } from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";

/** What the sandbox's code imports of autk-grammar's data entry, its own. */
const { createDataAdapter, enterWorkspace, tableKey } = require("@urban-toolkit/autk-grammar/data");

/** Ridership by station, a CSV with no geometry columns; the stations, one with them; and stops, JSON with none, in `east`. */
const SECTION = [
  { type: "csv", outputTableName: "ridership", csvObject: [["name", "riders"], ["Clark/Lake", 11000], ["Quincy", 7000]] },
  {
    type: "csv", outputTableName: "stations", csvObject: [["name", "lat", "lon"], ["Clark/Lake", 41.8857, -87.6309]],
    geometryColumns: { latColumnName: "lat", longColumnName: "lon" },
  },
  { type: "json", outputTableName: "stops", workspace: "east", jsonObject: [{ name: "Union", riders: 3 }, { name: "Ogilvie", riders: 5 }] },
];

/** What both loaders hand on of each table with no geometry: its rows, no layer type. */
const RIDERSHIP = {
  name: "ridership",
  geojson: {
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: null, properties: { name: "Clark/Lake", riders: 11000 } },
      { type: "Feature", geometry: null, properties: { name: "Quincy", riders: 7000 } },
    ],
  },
};
const STOPS = {
  name: "stops",
  workspace: "east",
  geojson: {
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: null, properties: { name: "Union", riders: 3 } },
      { type: "Feature", geometry: null, properties: { name: "Ogilvie", riders: 5 } },
    ],
  },
};

/** Run the section's compiled code as the sandbox runs it: its imports dropped. */
async function runInSandbox(sources: any[]): Promise<any[]> {
  const body = compileDataSpecToAutkDbJs(sources).replace(/^import [^\n]*\n/gm, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  return new AsyncFunction(
    "AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "createDataAdapter", "enterWorkspace", "tableKey", body,
  )(mockPlainTablesDb, "EPSG:3395", createDataAdapter, enterWorkspace, tableKey);
}

beforeEach(() => {
  mockFetchData.mockReset();
});

describe.each([
  ["the sandbox's loader", runInSandbox],
  ["the browser's loader", (sources: any[]) => loadSpecLayers({ data: sources })],
])("%s", (_loader, load) => {
  test("hands on a CSV or JSON table with no geometry as its rows, in its workspace, beside a CSV's layer", async () => {
    const handed = await load(SECTION);
    const named = (name: string) => handed.find((table: any) => table.name === name);
    expect(named("ridership")).toEqual(RIDERSHIP);
    expect(named("stops")).toEqual(STOPS);
    // A CSV with geometry columns is a layer, handed on with its type.
    expect(named("stations")).toEqual(expect.objectContaining({ name: "stations", type: "points" }));
    expect(named("stations").geojson.features.map((f: any) => f.geometry)).toEqual([{ type: "Point", coordinates: [-87.6309, 41.8857] }]);
    expect(handed.map((table: any) => table.name).sort()).toEqual(["ridership", "stations", "stops"]);
  });
});
