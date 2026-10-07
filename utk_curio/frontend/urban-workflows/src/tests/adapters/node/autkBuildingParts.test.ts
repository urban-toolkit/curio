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
 */
import * as fs from "fs";
import * as path from "path";

import { compileDataSpecToAutkDbJs } from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";

jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
// Virtual, as the other suites mock Autark: keyed by the package's name, so the
// loader's import of it gets this whatever its `exports` resolve to under Jest.
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  AutkDb: jest.fn().mockImplementation(() => new mockAutkDb()),
}), { virtual: true });

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

class mockAutkDb {
  init() { return Promise.resolve(); }
  loadOsm() { return Promise.resolve(); }
  getLayersMetadata() { return [{ name: "table_osm_buildings", type: "buildings" }]; }
  getLayer() { return Promise.resolve(mockBuildings()); }
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
  const body = code.replace(/^import [^\n]*\n/, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  const run = new AsyncFunction("AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", body);
  const layers = await run(mockAutkDb, "EPSG:3395");
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
});

test("examples 06 and 07 pack each part's outer ring, the path these rows answer", () => {
  for (const file of ["06-autark-what-if-shadow-study.json", "07-autark-gpu-shader.json"]) {
    const text = fs.readFileSync(path.join(EXAMPLES_DIR, file), "utf8");
    expect(text).toContain('\\"path\\": \\"geometry.coordinates.0\\"');
  }
});
