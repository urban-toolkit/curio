/**
 * An Autark node hands on every OpenStreetMap feature with its OSM id in an
 * `osm_id` column, as the Discovery Catalog's OpenStreetMap downloads name a
 * row, so an Interaction node or a selection can name an OSM road, park or
 * water by it (#1055). autk-db 4 gives a road's, a park's or a water's OSM id
 * as the feature's GeoJSON `id`, which a table leaves out, and a building
 * part's as that part's `id` in `properties.parts`. Both loaders hand the same
 * rows on: the sandbox's (compileDataSpecToAutkDbJs), which a run on the
 * server posts, and the in-browser fallback (loadSpecLayers).
 */
import { compileDataSpecToAutkDbJs } from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";

jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
// Virtual, as the other suites mock Autark: keyed by the package's name, so the
// loader's import of it gets this whatever its `exports` resolve to under Jest.
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  AutkDb: jest.fn().mockImplementation(() => new mockAutkDb()),
}), { virtual: true });

// Back Bay, in EPSG:3395 metres, as autk-db's workspace holds it.
const X = -7910000;
const Y = 5180000;
const line = (x: number) => ({ type: "LineString", coordinates: [[X + x, Y], [X + x + 50, Y + 10]] });
const square = (x: number, y: number, size: number) => ({
  type: "Polygon",
  coordinates: [[[X + x, Y + y], [X + x + size, Y + y], [X + x + size, Y + y + size], [X + x, Y + y + size], [X + x, Y + y]]],
});
const feature = (id: number | undefined, geometry: any, properties: any) => ({
  type: "Feature", ...(id === undefined ? {} : { id }), geometry, properties,
});
const collection = (features: any[]) => ({ type: "FeatureCollection", features });

/** What autk-db 4.1.1's getLayer gives for each table: an OpenStreetMap
 * element's id as the feature's `id`, its tags as its properties. */
const GIVEN: Record<string, () => any> = {
  // The area's land, no OpenStreetMap element: autk-db gives it no id.
  table_osm_surface: () => collection([feature(undefined, square(-500, -500, 2000), {})]),
  table_osm_parks: () => collection([
    feature(22977372, square(0, 300, 80), { leisure: "park", name: "Commonwealth Avenue Mall" }),
    // A multipolygon relation, named by the relation's id.
    feature(1592536, { type: "MultiPolygon", coordinates: [square(400, 300, 60).coordinates] },
      { leisure: "park", name: "Back Bay Fens", type: "multipolygon" }),
  ]),
  table_osm_water: () => collection([
    feature(4567890, square(0, 600, 300), { natural: "water", name: "Charles River" }),
  ]),
  table_osm_roads: () => collection([
    feature(8614929, line(0), { highway: "primary", name: "Boylston Street" }),
    feature(8615390, line(100), { highway: "residential", name: "Marlborough Street", oneway: "yes" }),
  ]),
  // Two buildings, as autk-db 4 keeps them: one feature each, its `id` and
  // `building_id` the building's, each part's id and tags in `parts`.
  table_osm_buildings: () => collection([
    feature(29623484, { type: "GeometryCollection", geometries: [square(0, 0, 40), square(40, 0, 20)] }, {
      building_id: 29623484,
      parts: [
        { geometryIndex: 1, id: 236608503, building: "yes", height: "30" },
        { geometryIndex: 0, id: 29623484, building: "yes", name: "200 Clarendon", height: "240.8" },
      ],
    }),
    feature(11, { type: "GeometryCollection", geometries: [square(100, 0, 10), square(120, 0, 10)] }, {
      building: "house",
      building_id: 11,
      parts: [
        { geometryIndex: 0, id: 11, building: "house", "building:height": "9" },
        { geometryIndex: 1, id: 12, building: "house", "building:levels": "2" },
      ],
    }),
  ]),
  // A GeoJSON source: autk-db keeps each feature's own id, which is no OSM id.
  zones: () => collection([
    feature(7, square(0, 0, 500), { zone: "B-1" }),
    feature(8, square(500, 0, 500), { zone: "B-2" }),
  ]),
  // A raster, as getRaster gives it: one feature with no geometry.
  table_heat: () => collection([
    feature(undefined, null, { rasterResX: 2, rasterResY: 1, raster: [{ band_1: 30.5 }, { band_1: 31 }] }),
  ]),
};

const TABLES = [
  { name: "table_osm_surface", type: "surface", source: "osm" },
  { name: "table_osm_parks", type: "parks", source: "osm" },
  { name: "table_osm_water", type: "water", source: "osm" },
  { name: "table_osm_roads", type: "roads", source: "osm" },
  { name: "table_osm_buildings", type: "buildings", source: "osm" },
  { name: "zones", type: "polygons", source: "geojson" },
  // autk-db lists no raster among its layers today; one handed on gains nothing.
  { name: "table_heat", type: "raster", source: "geotiff" },
];

/** What getLayer gives, per table, for the test running: GIVEN, or a test's own. */
let mockGiven: Record<string, () => any> = GIVEN;

class mockAutkDb {
  init() { return Promise.resolve(); }
  loadOsm() { return Promise.resolve(); }
  loadGeojson() { return Promise.resolve(); }
  getLayersMetadata() { return TABLES.map((table) => ({ ...table, columns: [] })); }
  getLayer(name: string) { return Promise.resolve(mockGiven[name]()); }
}

beforeEach(() => { mockGiven = GIVEN; });

const SOURCES = [
  {
    type: "osm",
    outputTableName: "table_osm",
    queryArea: { geocodeArea: "Boston", areas: ["Back Bay"] },
    autoLoadLayers: { layers: ["surface", "parks", "water", "roads", "buildings"] },
    pbfFileUrl: "docs/examples/data/back_bay.osm.pbf",
  },
  { type: "geojson", outputTableName: "zones", geojsonObject: GIVEN.zones() },
];

/** Each layer's features, by table name. */
type Layers = Record<string, any[]>;

const byName = (layers: Array<{ name: string; geojson: any }>): Layers =>
  Object.fromEntries(layers.map((layer) => [layer.name, layer.geojson.features]));

/** The layers the sandbox's code hands on, run as the sandbox runs it. */
async function sandboxLayers(): Promise<Layers> {
  const body = compileDataSpecToAutkDbJs(SOURCES).replace(/^import [^\n]*\n/, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  return byName(await new AsyncFunction("AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", body)(mockAutkDb, "EPSG:3395"));
}

/** The same, from the in-browser loader. */
async function browserLayers(): Promise<Layers> {
  return byName(await loadSpecLayers({ data: SOURCES }) as any);
}

const rows = (layers: Layers, name: string) => layers[name].map((f: any) => f.properties);

describe.each([
  ["the sandbox's loader", sandboxLayers],
  ["the in-browser loader", browserLayers],
])("%s", (_name, layersOf) => {
  test("hands on every feature of an OSM roads, parks or water layer with its OSM id as osm_id, and its tags", async () => {
    const layers = await layersOf();
    expect(rows(layers, "table_osm_roads")).toEqual([
      { highway: "primary", name: "Boylston Street", osm_id: 8614929 },
      { highway: "residential", name: "Marlborough Street", oneway: "yes", osm_id: 8615390 },
    ]);
    expect(rows(layers, "table_osm_parks")).toEqual([
      { leisure: "park", name: "Commonwealth Avenue Mall", osm_id: 22977372 },
      { leisure: "park", name: "Back Bay Fens", type: "multipolygon", osm_id: 1592536 },
    ]);
    expect(rows(layers, "table_osm_water")).toEqual([
      { natural: "water", name: "Charles River", osm_id: 4567890 },
    ]);
  });

  test("hands on every building part with its own part's OSM id as osm_id, and its building_id", async () => {
    const layers = await layersOf();
    expect(rows(layers, "table_osm_buildings")).toEqual([
      { building: "yes", name: "200 Clarendon", height: "240.8", osm_id: 29623484, building_id: 29623484 },
      { building: "yes", height: "30", osm_id: 236608503, building_id: 29623484 },
      { building: "house", "building:height": "9", osm_id: 11, building_id: 11 },
      { building: "house", "building:levels": "2", osm_id: 12, building_id: 11 },
    ]);
  });

  test("a feature or a part that already has an osm_id keeps it", async () => {
    mockGiven = {
      ...GIVEN,
      table_osm_water: () => collection([
        feature(4567890, square(0, 600, 300), { natural: "water", name: "Charles River", osm_id: 41 }),
      ]),
      table_osm_buildings: () => collection([
        feature(11, { type: "GeometryCollection", geometries: [square(100, 0, 10)] }, {
          building_id: 11,
          parts: [{ geometryIndex: 0, id: 11, building: "house", "building:levels": "2", osm_id: 42 }],
        }),
      ]),
    };
    const layers = await layersOf();
    expect(rows(layers, "table_osm_water")).toEqual([{ natural: "water", name: "Charles River", osm_id: 41 }]);
    expect(rows(layers, "table_osm_buildings")).toEqual([
      { building: "house", "building:levels": "2", osm_id: 42, building_id: 11 },
    ]);
  });

  test("a layer not from OpenStreetMap, the surface and a raster are handed on as they came", async () => {
    const layers = await layersOf();
    expect(layers.zones).toEqual(GIVEN.zones().features);
    expect(layers.table_osm_surface).toEqual(GIVEN.table_osm_surface().features);
    expect(layers.table_heat).toEqual(GIVEN.table_heat().features);
  });
});

test("the sandbox hands on the very rows the browser does", async () => {
  const [sandbox, browser] = [await sandboxLayers(), await browserLayers()];
  expect(Object.keys(sandbox)).toEqual(TABLES.map((table) => table.name));
  expect(sandbox).toEqual(browser);
});
