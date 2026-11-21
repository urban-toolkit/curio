/**
 * An Autark node hands on OpenStreetMap's numeric building tags as numbers.
 * autk-db keeps every tag as text ("65.5", "86 m"), and a Map Editor's rule or
 * expression (`height > 100`, `height * 0.5`), a Python node and a compute
 * pass read a text as a text: a length becomes metres, a level a number, and a
 * value that holds no number that can be read becomes null
 * (autkOsmNumbers.cases.json, the shared cases). Both loaders hand their
 * tables on through one function, `withOsmNumbers`: the sandbox's
 * (compileDataSpecToAutkDbJs, which embeds its source), which a run on the
 * server posts, and the in-browser fallback (loadSpecLayers). Each shared case
 * is a building part's tag here, read by both.
 */
import CASES from "../../../adapters/node/autkOsmNumbers.cases.json";
import { compileDataSpecToAutkDbJs, osmNumber, withOsmNumbers } from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";

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

type Case = { name: string; key: string; value: unknown; becomes: unknown };
const cases: Case[] = (CASES as { cases: Case[] }).cases;

// Back Bay, in EPSG:3395 metres, as autk-db's workspace holds it.
const X = -7910000;
const Y = 5180000;
const square = (x: number, y: number, size: number) => ({
  type: "Polygon",
  coordinates: [[[X + x, Y + y], [X + x + size, Y + y], [X + x + size, Y + y + size], [X + x, Y + y + size], [X + x, Y + y]]],
});
const feature = (id: number | undefined, geometry: any, properties: any) => ({
  type: "Feature", ...(id === undefined ? {} : { id }), geometry, properties,
});
const collection = (features: any[]) => ({ type: "FeatureCollection", features });

/** The OSM id of the building of case *i*, and of its one part. */
const idOf = (i: number) => 1000 + i;

/** What autk-db 4.1.1's getLayer gives for each table. */
const GIVEN: Record<string, () => any> = {
  // A building a case, as autk-db 4 keeps one: its `id` and `building_id` the
  // building's, its one part's id and tags, the case's tag among them, in `parts`.
  table_osm_buildings: () => collection(cases.map((c, i) => feature(
    idOf(i),
    { type: "GeometryCollection", geometries: [square(20 * i, 0, 10)] },
    { building_id: idOf(i), parts: [{ geometryIndex: 0, id: idOf(i), building: "yes", [c.key]: c.value }] },
  ))),
  // A park OpenStreetMap gives a height and a level, which are no building's.
  table_osm_parks: () => collection([
    feature(22977372, square(0, 300, 80), { leisure: "park", name: "Commonwealth Avenue Mall", height: "4 m", "building:levels": "1" }),
  ]),
  // The area's land, no OpenStreetMap element.
  table_osm_surface: () => collection([feature(undefined, square(-500, -500, 2000), {})]),
  // A GeoJSON source holds the text it was given.
  zones: () => collection([feature(7, square(0, 0, 500), { zone: "B-1", height: "86 m" })]),
};

const TABLES = [
  { name: "table_osm_surface", type: "surface", source: "osm" },
  { name: "table_osm_parks", type: "parks", source: "osm" },
  { name: "table_osm_buildings", type: "buildings", source: "osm" },
  { name: "zones", type: "polygons", source: "geojson" },
];

class mockAutkDb {
  init() { return Promise.resolve(); }
  // The default workspace, which the grammar's data adapter enters.
  getCurrentWorkspace() { return "autk"; }
  setWorkspace() { return Promise.resolve(); }
  loadOsm() { return Promise.resolve(); }
  loadGeojson() { return Promise.resolve(); }
  getLayersMetadata() { return TABLES.map((table) => ({ ...table, columns: [] })); }
  getLayer(name: string) { return Promise.resolve(GIVEN[name]()); }
}

const SOURCES = [
  {
    type: "osm",
    outputTableName: "table_osm",
    queryArea: { geocodeArea: "Boston", areas: ["Back Bay"] },
    autoLoadLayers: { layers: ["surface", "parks", "buildings"] },
    pbfFileUrl: "docs/examples/data/back_bay.osm.pbf",
  },
  { type: "geojson", outputTableName: "zones", coordinateFormat: "EPSG:3395", geojsonObject: GIVEN.zones() },
];

/** Each layer's features, by table name. */
type Layers = Record<string, any[]>;

const byName = (layers: Array<{ name: string; geojson: any }>): Layers =>
  Object.fromEntries(layers.map((layer) => [layer.name, layer.geojson.features]));

/** The layers the sandbox's code hands on, run as the sandbox runs it. */
async function sandboxLayers(): Promise<Layers> {
  // Its imports dropped, theirs handed in: autk-db's and the grammar's data entry's.
  const body = compileDataSpecToAutkDbJs(SOURCES).replace(/^import [^\n]*\n/gm, "");
  // The engine's own AsyncFunction: babel compiles an `async function` written
  // in this file to a generator, whose constructor is plain Function.
  const AsyncFunction = new Function("return (async () => {}).constructor")();
  return byName(await new AsyncFunction("AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "createDataAdapter", body)(
    mockAutkDb, "EPSG:3395", createDataAdapter,
  ));
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
  test("hands on each building part's tag as the shared cases say, one part a case", async () => {
    const parts = rows(await layersOf(), "table_osm_buildings");
    expect(parts).toHaveLength(cases.length);
    const handed = parts.map((part: any, i: number) => ({ name: cases[i].name, value: part[cases[i].key] }));
    expect(handed).toEqual(cases.map((c) => ({ name: c.name, value: c.becomes })));
    // Each part keeps its key, its OSM id and its building's id.
    parts.forEach((part: any, i: number) => {
      expect(Object.keys(part).sort()).toEqual(["building", "building_id", cases[i].key, "osm_id"].sort());
      expect(part.osm_id).toBe(idOf(i));
    });
  });

  test("hands on a height and a level of any OpenStreetMap layer as numbers", async () => {
    expect(rows(await layersOf(), "table_osm_parks")).toEqual([
      { leisure: "park", name: "Commonwealth Avenue Mall", height: 4, "building:levels": 1, osm_id: 22977372 },
    ]);
  });

  test("hands on the surface and a layer from another source as they came", async () => {
    const layers = await layersOf();
    expect(layers.table_osm_surface).toEqual(GIVEN.table_osm_surface().features);
    expect(rows(layers, "zones")).toEqual([{ zone: "B-1", height: "86 m" }]);
  });
});

test("the sandbox hands on the very rows the browser does", async () => {
  const [sandbox, browser] = [await sandboxLayers(), await browserLayers()];
  expect(Object.keys(sandbox)).toEqual(TABLES.map((table) => table.name));
  expect(sandbox).toEqual(browser);
});

describe("withOsmNumbers, the one function both loaders hand their layers on through", () => {
  test.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(osmNumber(c.key, c.value)).toEqual(c.becomes);
  });

  test("the sandbox's code embeds its own source", () => {
    expect(compileDataSpecToAutkDbJs(SOURCES)).toContain(`const __withOsmNumbers = ${withOsmNumbers.toString()};`);
  });

  test("reads a building's own tags and each of its parts' alike", () => {
    const given = [feature(29623484, { type: "GeometryCollection", geometries: [square(0, 0, 40), square(40, 0, 20)] }, {
      building_id: 29623484,
      height: "241m",
      "building:levels": "63",
      parts: [
        { geometryIndex: 0, id: 29623484, height: "241m", "building:levels": "63" },
        { geometryIndex: 1, id: 236608503, height: "30", "roof:height": "3 m", name: "Podium" },
      ],
    })];
    expect(withOsmNumbers({ source: "osm", type: "buildings" }, given)[0].properties).toEqual({
      building_id: 29623484,
      height: 241,
      "building:levels": 63,
      parts: [
        { geometryIndex: 0, id: 29623484, height: 241, "building:levels": 63 },
        { geometryIndex: 1, id: 236608503, height: 30, "roof:height": 3, name: "Podium" },
      ],
    });
  });

  test("never changes the features it is handed", () => {
    for (const [name, type] of [["table_osm_buildings", "buildings"], ["table_osm_parks", "parks"]]) {
      const given = GIVEN[name]().features;
      const before = JSON.parse(JSON.stringify(given));
      expect(withOsmNumbers({ source: "osm", type }, given)).not.toEqual(before);
      expect(given).toEqual(before);
    }
  });

  test("hands a feature back as it came when none of its tags changes", () => {
    const given = [
      feature(1, square(0, 0, 10), { height: 30, "building:levels": 9, name: "Numbers already" }),
      feature(2, square(20, 0, 10), { building_id: 2, parts: [{ geometryIndex: 0, id: 2, height: null }] }),
      feature(3, square(40, 0, 10), null),
      null,
    ];
    const handed = withOsmNumbers({ source: "osm", type: "buildings" }, given);
    handed.forEach((item, i) => expect(item).toBe(given[i]));
  });

  test("hands the surface, a raster and a layer from another source back as they came", () => {
    const given = GIVEN.zones().features;
    for (const table of [
      { source: "osm", type: "surface" },
      { source: "osm", type: "raster" },
      { source: "geojson", type: "polygons" },
      { source: "csv", type: "points" },
      {},
      null,
    ]) {
      expect(withOsmNumbers(table, given)).toBe(given);
    }
  });
});
