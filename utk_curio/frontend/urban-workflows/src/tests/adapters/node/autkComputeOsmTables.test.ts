/**
 * A compute step that runs on a database of its own (a pass with `writeBack`,
 * or sources after compute; adapters/node/autkComputeDatabase.ts) hands on a
 * table an OpenStreetMap source after compute loads as both loaders hand one
 * on: each feature with its OSM id in `osm_id`, a building part with its own,
 * its numeric building tags as numbers (`withOsmIds`, `withOsmNumbers` in
 * autkDataCompile.ts), and a building a part a row.
 *
 * The step runs through autk-grammar's own data adapter, the build the app
 * bundles (_support/autkComputeStandIns), on a stand-in autk-db that keeps
 * each table it is handed and loads an OpenStreetMap source's layers as
 * autk-db 4.1.1 exports them: every tag as text, a building as one feature
 * whose parts carry their ids and tags.
 */
jest.mock("@urban-toolkit/autk-grammar", () => require("../../_support/autkComputeStandIns").grammarBuild(), { virtual: true });
jest.mock("@urban-toolkit/autk-compute", () => require("../../_support/autkComputeStandIns").autkComputeModule, { virtual: true });
jest.mock("@urban-toolkit/autk-core", () => require("../../_support/autkComputeStandIns").autkCoreBuild(), { virtual: true });
jest.mock("@urban-toolkit/autk-map", () => require("../../_support/autkComputeStandIns").autkMapModule, { virtual: true });
jest.mock("@urban-toolkit/autk-plot", () => require("../../_support/autkComputeStandIns").autkPlotModule, { virtual: true });
jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));

/** What the stand-in autk-db keeps: each table, by name, with its type and its source. */
const mockTables = new Map<string, { type?: string; source: string; collection: any }>();
const mockCopy = (value: unknown) => JSON.parse(JSON.stringify(value));
const mockSquare = (x: number, size: number) => ({
  type: "Polygon",
  coordinates: [[[x, 0], [x + size, 0], [x + size, size], [x, size], [x, 0]]],
});
/** Each layer an OpenStreetMap load makes, as autk-db 4.1.1's getLayer exports it. */
const mockOsmLayers: Record<string, { type: string; collection: any }> = {
  buildings: {
    type: "buildings",
    collection: {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        id: 29623484,
        geometry: { type: "GeometryCollection", geometries: [mockSquare(0, 4), mockSquare(4, 2)] },
        properties: {
          building_id: 29623484,
          parts: [
            { geometryIndex: 0, id: 29623484, building: "yes", name: "200 Clarendon", height: "241m", "building:levels": "63" },
            { geometryIndex: 1, id: 236608503, building: "yes", height: "30", "roof:height": "3 m", "building:levels": "7-7" },
          ],
        },
      }],
    },
  },
  roads: {
    type: "roads",
    collection: {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        id: 8614929,
        geometry: { type: "LineString", coordinates: [[0, 10], [5, 11]] },
        properties: { highway: "primary", name: "Boylston Street", maxspeed: "25 mph" },
      }],
    },
  },
};
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
        mockTables.set(params.outputTableName, {
          type: params.layerType, source: "geojson", collection: mockCopy(params.geojsonObject),
        });
      }
      // An OpenStreetMap source: a table of each layer it names, as autk-db names them.
      async loadOsm(params: any) {
        for (const layer of params.autoLoadLayers.layers) {
          const made = mockOsmLayers[layer];
          mockTables.set(`${params.outputTableName}_${layer}`, {
            type: made.type, source: "osm", collection: mockCopy(made.collection),
          });
        }
      }
      async getBoundingBoxFromLayer() {
        return { minLon: 0, minLat: 0, maxLon: 50, maxLat: 5 };
      }
      getTablesMetadata() {
        return [...mockTables].map(([name, table]) => ({ name, type: table.type, source: table.source, columns: [] }));
      }
      async getLayer(name: string) {
        const table = mockTables.get(name);
        if (!table) throw new Error(`Table ${name} not found.`);
        return mockCopy(table.collection);
      }
    },
  }),
  { virtual: true },
);

import { applyComputeBlocks } from "../../../adapters/node/autkComputeBlocks";
import { resetComputeStandIns } from "../../_support/autkComputeStandIns";

/** Three points, each with a `value`: the layer the step holds. */
const spots = () => ({
  type: "FeatureCollection",
  features: [1, 2, 3].map((value, i) => ({ type: "Feature", geometry: { type: "Point", coordinates: [i, i] }, properties: { value } })),
});

/** Back Bay's buildings and roads, loaded after compute. */
const OSM_AFTER = {
  type: "osm",
  outputTableName: "table_osm",
  queryArea: { geocodeArea: "Boston", areas: ["Back Bay"] },
  autoLoadLayers: { layers: ["buildings", "roads"] },
  pbfFileUrl: "docs/examples/data/back_bay.osm.pbf",
  after: "compute",
};

/** What the step hands on, by table name. */
async function handedOn(): Promise<Record<string, any>> {
  const failures: string[] = [];
  const out = await applyComputeBlocks(
    [{ name: "spots", type: "points", geojson: spots() }] as any, [], failures, { after: [OSM_AFTER] },
  );
  expect(failures).toEqual([]);
  return Object.fromEntries(out.map((layer) => [layer.name, layer]));
}

beforeEach(() => {
  resetComputeStandIns();
  mockTables.clear();
});

describe("a compute step on a database of its own hands on an OpenStreetMap source after compute as the loaders do", () => {
  test("each building part with its own OSM id and its heights and levels as numbers, a part a row", async () => {
    const buildings = (await handedOn()).table_osm_buildings;
    expect(buildings.type).toBe("buildings");
    expect(buildings.geojson.features.map((f: any) => f.properties)).toEqual([
      { building: "yes", name: "200 Clarendon", height: 241, "building:levels": 63, osm_id: 29623484, building_id: 29623484 },
      { building: "yes", height: 30, "roof:height": 3, "building:levels": null, osm_id: 236608503, building_id: 29623484 },
    ]);
  });

  test("each road with its OSM id, its other tags as they came", async () => {
    const roads = (await handedOn()).table_osm_roads;
    expect(roads.geojson.features.map((f: any) => f.properties)).toEqual([
      { highway: "primary", name: "Boylston Street", maxspeed: "25 mph", osm_id: 8614929 },
    ]);
  });
});
