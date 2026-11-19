/**
 * autk-db 4 refuses a table in which a row's geometry is missing. Every path
 * that hands autk-db a table gives such a row an empty geometry instead: a
 * node's inputs, through `loadableFeatures` (`loadableSource`, tested in
 * utils/autkInput.test.ts), and a data section's GeoJSON sources, through
 * autk-grammar's own data adapter, which both loaders load every source with:
 * run in the sandbox and in the browser (loadSpecLayers). The grammar's rule is
 * the same, and gives each row the feature id autk-db gives it, from its place
 * in the source.
 */
import { compileDataSpecToAutkDbJs, loadableFeatures } from "../../../adapters/node/autkDataCompile";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";

jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
// Virtual, as the other suites mock Autark: keyed by the package's name.
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  DEFAULT_WORKSPACE_NAME: "autk",
  AutkDb: jest.fn().mockImplementation(() => new mockAutkDb()),
}), { virtual: true });

/** autk-grammar's data adapter, which both loaders load every source with. */
const { createDataAdapter } = jest.requireActual("@urban-toolkit/autk-grammar/data");

/** What each loadGeojson call was handed, in order. */
const mockLoaded: any[] = [];

class mockAutkDb {
  init() { return Promise.resolve(); }
  // The default workspace, which the grammar's data adapter enters.
  getCurrentWorkspace() { return "autk"; }
  setWorkspace() { return Promise.resolve(); }
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

describe("a data section's GeoJSON sources go through the grammar's rule, the same, with each row's feature id", () => {
  const rows = () => [row(null, 0), row(point(1, 1), 1), row(null, 2)];
  // The rule's rows, each with the id autk-db gives the row it was:
  // `autk-feature-<its place in the source>`.
  const { features: loadable, order } = loadableFeatures(rows());
  const expected = loadable.map((feature, at) => ({ ...feature, id: `autk-feature-${order ? order[at] : at}` }));
  const inline = () => [{
    type: "geojson",
    outputTableName: "rows",
    geojsonObject: { type: "FeatureCollection", features: rows() },
  }];
  const fromFile = () => [{ type: "geojson", outputTableName: "rows", geojsonFileUrl: "http://backend/file/rows.geojson" }];
  const stubFetch = jest.fn(async () => ({ json: async () => ({ type: "FeatureCollection", features: rows() }) }));

  /**
   * The sandbox's code, run as the sandbox runs it: its imports dropped,
   * theirs handed in. The grammar's data adapter fetches a source's file with
   * the page's own `fetch`.
   */
  async function runInSandbox(sources: any[]) {
    const body = compileDataSpecToAutkDbJs(sources).replace(/^import [^\n]*\n/gm, "");
    // The engine's own AsyncFunction: babel compiles an `async function` written
    // in this file to a generator, whose constructor is plain Function.
    const AsyncFunction = new Function("return (async () => {}).constructor")();
    await new AsyncFunction("AutkDb", "DEFAULT_WORKSPACE_COORDINATE_FORMAT", "createDataAdapter", body)(
      mockAutkDb, "EPSG:3395", createDataAdapter,
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
    const saved = (globalThis as any).fetch;
    (globalThis as any).fetch = stubFetch;
    try {
      await runInSandbox(fromFile());
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
    // Each with the id of the row it was.
    expect(expected.map((f) => f.id)).toEqual(["autk-feature-1", "autk-feature-0", "autk-feature-2"]);
  });
});
