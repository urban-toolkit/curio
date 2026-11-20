/**
 * An Autark data node hands buildings on as one row per part (#536). autk-db 4
 * keeps a building as ONE feature, a GeometryCollection, with each part's tags
 * in `properties.parts` naming its geometry by `geometryIndex`. Both loaders
 * split it the same way: the sandbox's (compileDataSpecToAutkDbJs) and the
 * in-browser fallback (loadSpecLayers).
 *
 * Examples 06 and 07 pack each part's `geometry.coordinates.0` into their
 * batched shadow step, which reads a Polygon's outer ring: a part handed on as
 * a GeometryCollection would pack a box of zero area.
 *
 * A part with no height is handed on at the height Curio gives it, which every
 * node reads, and names that height (`MADE_HEIGHT`), so a map layer with
 * `buildingsZeroHeight` takes it back and autk-map raises the part at random.
 */
import * as fs from "fs";
import * as path from "path";

import { MADE_HEIGHT, compileDataSpecToAutkDbJs } from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";
import { autkSourcesFrom } from "../../../utils/autkInput";
import type { GrammarFrame } from "../../../utils/grammarInput";

jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
// Virtual, as the other suites mock Autark: keyed by the package's name, so the
// loader's import of it gets this whatever its `exports` resolve to under Jest.
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  DEFAULT_WORKSPACE_NAME: "autk",
  AutkDb: jest.fn().mockImplementation(() => new mockAutkDb()),
}), { virtual: true });

/** autk-grammar's data adapter, which both loaders load every source with. */
const { createDataAdapter } = jest.requireActual("@urban-toolkit/autk-grammar/data");

const EXAMPLES_DIR = path.join(__dirname, "..", "..", "..", "..", "..", "..", "..", "docs", "examples");

// Back Bay, in EPSG:3395 metres, as autk-db's workspace holds it.
const X = -7910000;
const Y = 5180000;
const square = (x: number, y: number, size: number) => ({
  type: "Polygon",
  coordinates: [[[X + x, Y + y], [X + x + size, Y + y], [X + x + size, Y + y + size], [X + x, Y + y + size], [X + x, Y + y]]],
});
const TOWER = square(0, 0, 40);
const PODIUM = square(40, 0, 20);
const HOUSE = square(100, 0, 10);
const WINGS = {
  type: "MultiPolygon",
  coordinates: [square(200, 0, 10).coordinates, square(220, 0, 10).coordinates],
};

/** Two buildings as autk-db 4's getLayer exports them. */
function mockBuildings() {
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: 29623484,
        geometry: { type: "GeometryCollection", geometries: [TOWER, PODIUM] },
        properties: {
          building_id: 29623484,
          parts: [
            // Listed against the order of the geometries: each part names its own.
            { geometryIndex: 1, id: 236608503, building: "yes", height: "30" },
            { geometryIndex: 0, id: 29623484, building: "yes", name: "200 Clarendon", height: "240.8" },
          ],
        },
      },
      {
        type: "Feature",
        id: 11,
        geometry: { type: "GeometryCollection", geometries: [HOUSE, WINGS] },
        properties: {
          building: "house",
          building_id: 11,
          parts: [
            { geometryIndex: 0, id: 11, building: "house", "building:height": "9" },
            { geometryIndex: 1, id: 12, building: "house", "building:levels": "2" },
          ],
        },
      },
    ],
  };
}

/** The rows each loader must hand on, in the order of the geometries. */
const EXPECTED = [
  { geometry: TOWER, properties: { building: "yes", name: "200 Clarendon", height: "240.8", building_id: 29623484 } },
  { geometry: PODIUM, properties: { building: "yes", height: "30", building_id: 29623484 } },
  { geometry: HOUSE, properties: { building: "house", "building:height": "9", building_id: 11 } },
  { geometry: WINGS, properties: { building: "house", "building:levels": "2", building_id: 11 } },
];

const SHED = square(300, 0, 10);
const ANNEX = square(320, 0, 10);

/** A building of two parts, the second with no height, as autk-db 4's getLayer exports it. */
function mockShed() {
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      id: 31,
      geometry: { type: "GeometryCollection", geometries: [SHED, ANNEX] },
      properties: {
        building_id: 31,
        parts: [
          { geometryIndex: 0, id: 31, building: "shed", height: "12" },
          { geometryIndex: 1, id: 32, building: "shed" },
        ],
      },
    }],
  };
}

/** The buildings the database exports. */
let mockExport: () => any = mockBuildings;

class mockAutkDb {
  init() { return Promise.resolve(); }
  // The default workspace, which the grammar's data adapter enters.
  getCurrentWorkspace() { return "autk"; }
  setWorkspace() { return Promise.resolve(); }
  loadOsm() { return Promise.resolve(); }
  getLayersMetadata() { return [{ name: "table_osm_buildings", type: "buildings" }]; }
  getLayer() { return Promise.resolve(mockExport()); }
}

const SOURCES = [{
  type: "osm",
  outputTableName: "table_osm",
  queryArea: { geocodeArea: "Boston", areas: ["Back Bay"] },
  autoLoadLayers: { layers: ["buildings"] },
  pbfFileUrl: "docs/examples/data/back_bay.osm.pbf",
}];

/** The buildings the sandbox's code hands on, run as the sandbox runs it. */
async function sandboxParts(): Promise<any[]> {
  const code = compileDataSpecToAutkDbJs(SOURCES);
  // Its imports dropped, theirs handed in: autk-db's and the grammar's data entry's.
  const body = code.replace(/^import [^\n]*\n/gm, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  const run = new AsyncFunction("AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "createDataAdapter", body);
  const layers = await run(mockAutkDb, "EPSG:3395", createDataAdapter);
  return layers.find((layer: any) => layer.name === "table_osm_buildings").geojson.features;
}

/** The same, from the in-browser loader. */
async function browserParts(): Promise<any[]> {
  const layers = await loadSpecLayers({ data: SOURCES });
  const buildings = layers.find((layer) => layer.name === "table_osm_buildings") as any;
  return buildings.geojson.features;
}

describe.each([
  ["the sandbox's loader", sandboxParts],
  ["the in-browser loader", browserParts],
])("%s", (_name, partsOf) => {
  test("hands on one row per part, with the tags of the part its geometryIndex names", async () => {
    const parts = await partsOf();
    expect(parts.map((part: any) => ({ geometry: part.geometry, properties: part.properties }))).toEqual(EXPECTED);
  });

  test("never hands on a GeometryCollection: a Polygon part packs its outer ring", async () => {
    for (const part of await partsOf()) {
      expect(["Polygon", "MultiPolygon"]).toContain(part.geometry.type);
      if (part.geometry.type !== "Polygon") continue;
      const ring = part.geometry.coordinates[0];
      const xs = ring.map((point: number[]) => point[0]);
      const ys = ring.map((point: number[]) => point[1]);
      expect(ring.length).toBeGreaterThanOrEqual(4);
      expect(Math.max(...xs)).toBeGreaterThan(Math.min(...xs));
      expect(Math.max(...ys)).toBeGreaterThan(Math.min(...ys));
    }
  });

  describe("a part with no height", () => {
    beforeEach(() => { mockExport = mockShed; });
    afterEach(() => { mockExport = mockBuildings; });

    test("is handed on at the height Curio gives it, which the part names; a part with its own names none", async () => {
      const [own, none] = await partsOf();
      expect(none.properties).toEqual({ building: "shed", building_id: 31, height: 6 });
      expect(none[MADE_HEIGHT]).toBe(6);
      expect(own.properties).toEqual({ building: "shed", height: "12", building_id: 31 });
      expect(MADE_HEIGHT in own).toBe(false);
    });

    test("a map layer with buildingsZeroHeight takes that height back, but not one changed since", async () => {
      const [own, none] = await partsOf();
      const raised = { ...none, properties: { ...none.properties, height: 20 } };
      const frame: GrammarFrame = {
        name: "table_osm_buildings",
        dataType: "geodataframe",
        payload: { type: "FeatureCollection", features: [own, none, raised] },
        schema: null,
        geometryName: "geometry",
        crsName: null,
        layerType: "buildings",
        fromBundle: false,
        index: 0,
        circle: 0,
      };
      const drawn = (layer: Record<string, unknown>) => autkSourcesFrom({ frames: [frame] }, {
        map: { layerRefs: [{ dataRef: "table_osm_buildings", ...layer }] },
      }).sources[0].geojsonObject.features.map((feature: any) => feature.properties);

      const zero = drawn({ buildingsZeroHeight: true });
      // No key autk-map reads a top from: it raises the part at random.
      expect(["height", "building:height", "levels", "building:levels"].filter((key) => key in zero[1])).toEqual([]);
      expect([zero[0].height, zero[2].height]).toEqual(["12", 20]);
      // Every other layer draws the part at the height Curio gave it.
      expect(drawn({}).map((properties: any) => properties.height)).toEqual(["12", 6, 20]);
    });
  });
});

test("examples 06 and 07 pack each part's outer ring, the path these rows answer", () => {
  for (const file of ["06-back-bay-road-sunlight.json", "07-autark-gpu-shader.json"]) {
    const text = fs.readFileSync(path.join(EXAMPLES_DIR, file), "utf8");
    expect(text).toContain('\\"path\\": \\"geometry.coordinates.0\\"');
  }
});
