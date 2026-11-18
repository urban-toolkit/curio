/**
 * autk-db 4 refuses a table in which a row's geometry is missing. Every path
 * that hands autk-db a table gives such a row an empty geometry instead, through
 * one function, `loadableFeatures`: a node's inputs (`loadableSource`, tested in
 * utils/autkInput.test.ts), and a data section's GeoJSON sources, run in the
 * sandbox (the emitted code embeds the function's own source) and in the
 * browser (loadSpecLayers).
 */
import { compileDataSpecToAutkDbJs, loadableFeatures } from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";

jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
// Virtual, as the other suites mock Autark: keyed by the package's name.
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  AutkDb: jest.fn().mockImplementation(() => new mockAutkDb()),
}), { virtual: true });

/** What each loadGeojson call was handed, in order. */
const mockLoaded: any[] = [];

class mockAutkDb {
  init() { return Promise.resolve(); }
  loadGeojson(params: any) { mockLoaded.push(params); return Promise.resolve(); }
  getLayersMetadata() { return []; }
  getLayer() { return Promise.resolve({ type: "FeatureCollection", features: [] }); }
}

const EMPTY = { type: "GeometryCollection", geometries: [] };
const point = (x: number, y: number) => ({ type: "Point", coordinates: [x, y] });
const row = (geometry: any, value: number) => ({ type: "Feature", geometry, properties: { value } });

beforeEach(() => { mockLoaded.length = 0; });

describe("loadableFeatures", () => {
  test("a row with no geometry gets the empty one, and every other row is the same object", () => {
    const rows = [row(point(0, 0), 0), row(null, 1), row(undefined, 2), row(point(3, 3), 3)];
    const { features, order } = loadableFeatures(rows);
    expect(order).toBeNull();
    expect(features.map((f) => f.geometry)).toEqual([point(0, 0), EMPTY, EMPTY, point(3, 3)]);
    expect(features[0]).toBe(rows[0]);
    expect(features[3]).toBe(rows[3]);
    expect(features[1]).toEqual({ type: "Feature", geometry: EMPTY, properties: { value: 1 } });
    expect(features[2]).toEqual({ type: "Feature", geometry: EMPTY, properties: { value: 2 } });
    // The input is never changed.
    expect(rows[1].geometry).toBeNull();
    expect(rows[2].geometry).toBeUndefined();
  });

  test("a first row with no geometry trades places with the first that has one", () => {
    const rows = [row(null, 0), row(null, 1), row(point(2, 2), 2), row(point(3, 3), 3)];
    const { features, order } = loadableFeatures(rows);
    expect(order).toEqual([2, 1, 0, 3]);
    expect(features.map((f) => f.properties.value)).toEqual([2, 1, 0, 3]);
    expect(features.map((f) => f.geometry)).toEqual([point(2, 2), EMPTY, EMPTY, point(3, 3)]);
    expect(features[0]).toBe(rows[2]);
  });

  test("rows that all have a geometry come back as the same array", () => {
    const rows = [row(point(0, 0), 0), row(point(1, 1), 1)];
    expect(loadableFeatures(rows)).toEqual({ features: rows, order: null });
    expect(loadableFeatures(rows).features).toBe(rows);
    expect(loadableFeatures([])).toEqual({ features: [], order: null });
  });
});

describe("a data section's GeoJSON sources go through the same rule", () => {
  const rows = () => [row(null, 0), row(point(1, 1), 1), row(null, 2)];
  const expected = loadableFeatures(rows()).features;
  const inline = () => [{
    type: "geojson",
    outputTableName: "rows",
    geojsonObject: { type: "FeatureCollection", features: rows() },
  }];
  const fromFile = () => [{ type: "geojson", outputTableName: "rows", geojsonFileUrl: "http://backend/file/rows.geojson" }];
  const stubFetch = jest.fn(async () => ({ json: async () => ({ type: "FeatureCollection", features: rows() }) }));

  /** The sandbox's code, run as the sandbox runs it (its one import dropped). */
  async function runInSandbox(sources: any[]) {
    const body = compileDataSpecToAutkDbJs(sources).replace(/^import [^\n]*\n/, "");
    // The engine's own AsyncFunction: babel compiles an `async function` written
    // in this file to a generator, whose constructor is plain Function.
    const AsyncFunction = new Function("return (async () => {}).constructor")();
    await new AsyncFunction("AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "fetch", body)(
      mockAutkDb, "EPSG:3395", stubFetch,
    );
  }

  test("in the sandbox", async () => {
    await runInSandbox(inline());
    expect(mockLoaded).toHaveLength(1);
    expect(mockLoaded[0].outputTableName).toBe("rows");
    expect(mockLoaded[0].geojsonObject.features).toEqual(expected);
  });

  test("in the browser", async () => {
    await loadSpecLayers({ data: inline() });
    expect(mockLoaded).toHaveLength(1);
    expect(mockLoaded[0].geojsonObject.features).toEqual(expected);
  });

  test("a source that names a file is read first, in the sandbox and in the browser", async () => {
    await runInSandbox(fromFile());
    const saved = (globalThis as any).fetch;
    (globalThis as any).fetch = stubFetch;
    try {
      await loadSpecLayers({ data: fromFile() });
    } finally {
      (globalThis as any).fetch = saved;
    }
    expect(stubFetch).toHaveBeenCalledWith("http://backend/file/rows.geojson");
    expect(mockLoaded).toHaveLength(2);
    for (const params of mockLoaded) {
      expect(params.geojsonFileUrl).toBeUndefined();
      expect(params.outputTableName).toBe("rows");
      expect(params.geojsonObject.features).toEqual(expected);
    }
  });

  test("the expected rows are the rule's: the second row first, the empty geometry for the others", () => {
    expect(expected.map((f) => f.properties.value)).toEqual([1, 0, 2]);
    expect(expected.map((f) => f.geometry)).toEqual([point(1, 1), EMPTY, EMPTY]);
  });
});
