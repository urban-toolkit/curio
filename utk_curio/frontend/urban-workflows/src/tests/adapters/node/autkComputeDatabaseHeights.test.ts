/**
 * A building part's height in a compute step that runs on a database of its
 * own (a pass with `writeBack`, or sources after compute;
 * adapters/node/autkComputeDatabase.ts), as in a step with none
 * (autkComputeBlocks):
 *
 * - a pass that reads every building's height with `required: true` reads a
 *   part with no height 6 m tall above its base, as a map draws it;
 * - a table a pass wrote over a buildings layer is handed on with each part's
 *   own height, none where it had none;
 * - a layer nothing changed is handed on as the step holds it;
 * - a buildings layer a source after compute joins into is read back with
 *   each part's own height: the part the step gave the default carries its
 *   mark through the join, as autk-db patches a row's properties;
 * - a part a source after compute gives a height of its own keeps it: the
 *   mark takes the default back off only a part that still holds it.
 *
 * The step runs through autk-grammar's own data and compute adapters, the
 * build the app bundles, on a stand-in autk-compute whose GPGPU dispatch writes
 * twice each feature's `value` (_support/autkComputeStandIns), and a stand-in
 * autk-db that keeps each table it is handed, counts its rows for the
 * grammar's check after a writeBack, joins as autk-db does, patching each root
 * row's properties with what it joined (`sjoin`), and saves the one query of
 * the test's own under a table's name.
 */
jest.mock("@urban-toolkit/autk-grammar", () => require("../../_support/autkComputeStandIns").grammarBuild(), { virtual: true });
jest.mock("@urban-toolkit/autk-compute", () => require("../../_support/autkComputeStandIns").autkComputeModule, { virtual: true });
jest.mock("@urban-toolkit/autk-core", () => require("../../_support/autkComputeStandIns").autkCoreBuild(), { virtual: true });
jest.mock("@urban-toolkit/autk-map", () => require("../../_support/autkComputeStandIns").autkMapModule, { virtual: true });
jest.mock("@urban-toolkit/autk-plot", () => require("../../_support/autkComputeStandIns").autkPlotModule, { virtual: true });
jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));

/** What the stand-in autk-db keeps: each table it was handed, by name, with its type. */
const mockTables = new Map<string, { type?: string; collection: any }>();
const mockCopy = (value: unknown) => JSON.parse(JSON.stringify(value));
jest.mock(
  "@urban-toolkit/autk-db",
  () => ({
    DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
    DEFAULT_WORKSPACE_NAME: "autk",
    isVectorTable: () => true,
    isRenderableTable: () => true,
    AutkDb: class {
      private workspace = "autk";
      async init() {}
      getCurrentWorkspace() {
        return this.workspace;
      }
      async setWorkspace(name: string) {
        this.workspace = name;
      }
      getWorkspaceConfiguration() {
        return { coordinateFormat: "EPSG:3395" };
      }
      async loadGeojson(params: any) {
        mockTables.set(params.outputTableName, { type: params.layerType, collection: mockCopy(params.geojsonObject) });
      }
      async getBoundingBoxFromLayer() {
        return { minLon: 0, minLat: 0, maxLon: 50, maxLat: 5 };
      }
      getTablesMetadata() {
        return [...mockTables].map(([name, table]) => ({ name, type: table.type, source: "geojson", columns: [] }));
      }
      async getLayer(name: string) {
        const table = mockTables.get(name);
        if (!table) throw new Error(`Table ${name} not found.`);
        return mockCopy(table.collection);
      }
      async updateTable({ tableName, data }: any) {
        mockTables.set(tableName, { type: mockTables.get(tableName)?.type, collection: mockCopy(data) });
      }
      // Two queries: a table saved under a name (CREATE_TABLE), its rows those
      // of the table it reads FROM with each row's properties patched as
      // `json_merge_patch(properties, '<patch>')` writes them, none when it
      // reads no table, as the grammar's empty table for a writeBack; and the
      // rows a table holds, which the grammar counts once it kept a pass's
      // result (SELECT count(*) AS n FROM "<table>").
      async rawQuery({ query, output }: any) {
        const from = /FROM "([^"]+)"/.exec(String(query))?.[1];
        const table = from ? mockTables.get(from) : undefined;
        if (output?.type === "CREATE_TABLE") {
          const patch = /json_merge_patch\(properties, '([^']*)'\)/.exec(String(query))?.[1];
          const features = (table?.collection.features ?? []).map((feature: any) => ({
            ...feature,
            properties: { ...feature.properties, ...(patch ? JSON.parse(patch) : {}) },
          }));
          mockTables.set(output.tableName, {
            type: output.tableType ?? table?.type,
            collection: { type: "FeatureCollection", features: mockCopy(features) },
          });
          return [];
        }
        return [{ n: table ? table.collection.features.length : 0 }];
      }
      // autk-db's spatial join: each root row's properties patched with what
      // it joined, under `sjoin` (json_merge_patch), every other key kept.
      async spatialQuery({ tableRootName }: any) {
        const root = mockTables.get(tableRootName)!;
        const features = root.collection.features.map((feature: any) => ({
          ...feature,
          properties: { ...feature.properties, sjoin: { matches: [] } },
        }));
        mockTables.set(tableRootName, { type: root.type, collection: { ...root.collection, features } });
      }
    },
  }),
  { virtual: true },
);

import { applyComputeBlocks } from "../../../adapters/node/autkComputeBlocks";
import { computeRuns, resetComputeStandIns } from "../../_support/autkComputeStandIns";

/** A footprint at place *i*, in degrees. */
const footprint = (i: number) => ({
  type: "Polygon",
  coordinates: [[[10 * i, 0], [10 * i + 5, 0], [10 * i + 5, 5], [10 * i, 0]]],
});
const collection = (properties: object[]) => ({
  type: "FeatureCollection",
  features: properties.map((props, i) => ({ type: "Feature", geometry: footprint(i), properties: props })),
});
/** Three points, each with a `value`. */
const spots = () => ({
  type: "FeatureCollection",
  features: [1, 2, 3].map((value, i) => ({ type: "Feature", geometry: { type: "Point", coordinates: [i, i] }, properties: { value } })),
});

/** The stand-in GPGPU dispatch: the table it runs over with twice each feature's `value` under `compute.<column>`. */
function computed(params: any): any {
  const source = params.collection;
  return {
    ...source,
    features: source.features.map((f: any) => ({
      ...f,
      properties: { ...f.properties, compute: { ...(f.properties?.compute ?? {}), [params.resultField]: 2 * Number(f.properties?.value ?? 0) } },
    })),
  };
}

/** A pass that writes twice each feature's `value` as *column*, and keeps its result in autk-db. */
const pass = (dataRef: string, column: string, more: object = {}) => ({
  dataRef, attributes: { v: "properties.value" }, wgslFunction: "return v * 2.0;", outputColumnName: column, writeBack: true, ...more,
});
/** Every building part's height, read with required: true. */
const HEIGHTS = { heights: { fromFeature: { layer: "blocks", iterate: "batched", path: "properties.height", required: true } } };

/** Points; buildings, one part with a height and one with none; a shed with none, which no pass reads. */
const layers = () => [
  { name: "spots", type: "points", geojson: spots() },
  { name: "blocks", type: "buildings", geojson: collection([{ height: 12, value: 1 }, { value: 2 }]) },
  { name: "sheds", type: "buildings", geojson: collection([{ value: 5 }]) },
];

beforeEach(() => {
  resetComputeStandIns();
  computeRuns.gpgpu.mockImplementation(async (params: any) => computed(params));
  mockTables.clear();
});

describe("a compute step on a database of its own reads a building's height as a step with none", () => {
  test("a pass that reads every building's height with required: true reads a part with no height 6 m tall", async () => {
    const failures: string[] = [];
    await applyComputeBlocks(layers() as any, [pass("spots", "twice", { uniforms: HEIGHTS })], failures);
    expect(failures).toEqual([]);
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
    const { uniforms, uniformArrays } = computeRuns.gpgpu.mock.calls[0][0];
    expect(uniforms.num_features).toBe(2);
    expect(uniformArrays.heights).toEqual([12, 6]);
  });

  test("a table a pass wrote over a buildings layer is handed on with each part's own height, none where it had none", async () => {
    const failures: string[] = [];
    const out = await applyComputeBlocks(layers() as any, [pass("blocks", "twice")], failures);
    expect(failures).toEqual([]);
    // What the pass read: the part with no height 6 m tall.
    expect(computeRuns.gpgpu.mock.calls[0][0].collection.features.map((f: any) => f.properties.height)).toEqual([12, 6]);
    // What the step hands on: the pass's column, and each part's own height.
    const blocks = out.find((layer) => layer.name === "blocks")!;
    expect(blocks.geojson.features.map((f: any) => f.properties)).toEqual([
      { height: 12, value: 1, compute: { twice: 2 }, twice: 2 },
      { value: 2, compute: { twice: 4 }, twice: 4 },
    ]);
  });

  test("a layer nothing changed is handed on as the step holds it, though its database held the default", async () => {
    const given = layers();
    const failures: string[] = [];
    const out = await applyComputeBlocks(given as any, [pass("spots", "twice")], failures);
    expect(failures).toEqual([]);
    const sheds = out.find((layer) => layer.name === "sheds")!;
    expect(sheds.geojson).toBe(given[2].geojson);
    expect(sheds.geojson.features.map((f: any) => f.properties)).toEqual([{ value: 5 }]);
    expect(mockTables.get("sheds")?.collection.features.map((f: any) => f.properties.height)).toEqual([6]);
  });

  test("a buildings layer a source after compute joins into is read back with each part's own height", async () => {
    const failures: string[] = [];
    const out = await applyComputeBlocks(
      layers() as any,
      [pass("spots", "twice", { uniforms: HEIGHTS })],
      failures,
      { after: [{ type: "join", dataRef: "blocks", joinDataRef: "spots", after: "compute" }] },
    );
    expect(failures).toEqual([]);
    // The pass read the part with no height 6 m tall, which the database
    // still holds after the join.
    expect(computeRuns.gpgpu.mock.calls[0][0].uniformArrays.heights).toEqual([12, 6]);
    expect(mockTables.get("blocks")?.collection.features.map((f: any) => f.properties.height)).toEqual([12, 6]);
    // The join's result, read back: each part with its own height, no mark.
    const blocks = out.find((layer) => layer.name === "blocks")!;
    expect(blocks.geojson.features.map((f: any) => f.properties)).toEqual([
      { height: 12, value: 1, sjoin: { matches: [] } },
      { value: 2, sjoin: { matches: [] } },
    ]);
  });

  test("a part a source after compute gives a height of its own keeps it, though the step gave it the default", async () => {
    const failures: string[] = [];
    // A SQL query saved under the buildings' name that sets every part 20 m tall.
    const query = `SELECT * REPLACE (json_merge_patch(properties, '{"height": 20}') AS properties) FROM "blocks"`;
    const out = await applyComputeBlocks(
      layers() as any,
      [pass("spots", "twice", { uniforms: HEIGHTS })],
      failures,
      { after: [{ type: "sql", query, outputTableName: "blocks", layerType: "buildings", after: "compute" }] },
    );
    expect(failures).toEqual([]);
    // The pass read the part with no height 6 m tall; the query then gave
    // both parts 20 m, which the step hands on, with no mark.
    expect(computeRuns.gpgpu.mock.calls[0][0].uniformArrays.heights).toEqual([12, 6]);
    const blocks = out.find((layer) => layer.name === "blocks")!;
    expect(blocks.geojson.features.map((f: any) => f.properties)).toEqual([
      { height: 20, value: 1 },
      { height: 20, value: 2 },
    ]);
  });
});
