/**
 * The paths that run part of an Autark document refuse a key autk-grammar 5
 * renamed, or one a node does not run yet, as the node's run does
 * (contracts/autkGrammar's autkKeyProblem): the compute of a compute-only node
 * (applyComputeBlocks) and the browser's loader of a data section
 * (loadSpecLayers). Neither runs any of it: no pass is dispatched and no
 * database is made.
 *
 * The passes run through autk-grammar's own compute code, the build the app
 * bundles, on a stand-in autk-compute that records each dispatch
 * (_support/autkComputeStandIns).
 */
const mockAutkDb = jest.fn();

jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
jest.mock("@urban-toolkit/autk-grammar", () => require("../../_support/autkComputeStandIns").grammarBuild(), { virtual: true });
jest.mock("@urban-toolkit/autk-compute", () => require("../../_support/autkComputeStandIns").autkComputeModule, { virtual: true });
jest.mock("@urban-toolkit/autk-core", () => require("../../_support/autkComputeStandIns").autkCoreBuild());
jest.mock("@urban-toolkit/autk-map", () => require("../../_support/autkComputeStandIns").autkMapModule);
jest.mock("@urban-toolkit/autk-plot", () => require("../../_support/autkComputeStandIns").autkPlotModule);
jest.mock("@urban-toolkit/autk-db", () => ({
  AutkDb: function AutkDb(...a: any[]) { return mockAutkDb(...a); },
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  DEFAULT_WORKSPACE_NAME: "autk",
}), { virtual: true });

import { applyComputeBlocks } from "../../../adapters/node/autkComputeBlocks";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";
import { computeRuns, resetComputeStandIns } from "../../_support/autkComputeStandIns";

const ROADS = {
  name: "input_0",
  type: "roads",
  geojson: {
    type: "FeatureCollection" as const,
    features: [{ type: "Feature" as const, properties: { lanes: 2 }, geometry: { type: "Point" as const, coordinates: [0, 0] } }],
  },
};
const PASS = { dataRef: "input_0", attributes: { x: "lanes" }, wgslFunction: "return x;", outputColumnName: "y" };

/** The GPGPU dispatch *pass* is: its table, attributes, shader and column. */
const dispatchOf = (pass: typeof PASS) => expect.objectContaining({
  collection: ROADS.geojson,
  variableMapping: pass.attributes,
  wgslBody: pass.wgslFunction,
  resultField: pass.outputColumnName,
});

beforeEach(() => {
  resetComputeStandIns();
  mockAutkDb.mockReset();
});

describe("applyComputeBlocks", () => {
  test.each([
    [
      "a pass written with wglsFunction",
      [{ ...PASS, wgslFunction: undefined, wglsFunction: "return x;" }],
      'This spec uses "wglsFunction" at compute[0], which autk-grammar 5 renamed to "wgslFunction".',
    ],
  ])("%s is a failure, named, and no pass runs", async (_what, passes, said) => {
    const failures: string[] = [];
    const layers = await applyComputeBlocks([ROADS], passes as any[], failures);
    expect(failures).toEqual([said]);
    expect(layers).toEqual([ROADS]);
    expect(computeRuns.gpgpu).not.toHaveBeenCalled();
    expect(computeRuns.render).not.toHaveBeenCalled();
  });

  test("guard: a pass of autk-grammar 5's keys runs", async () => {
    computeRuns.gpgpu.mockResolvedValue(ROADS.geojson);
    const failures: string[] = [];
    await applyComputeBlocks([ROADS], [PASS], failures);
    expect(failures).toEqual([]);
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
    expect(computeRuns.gpgpu.mock.calls[0][0]).toEqual(dispatchOf(PASS));
  });

  test("a pass that writes a new table, with its type, runs", async () => {
    computeRuns.gpgpu.mockResolvedValue(ROADS.geojson);
    const failures: string[] = [];
    const written = { ...PASS, outputTableName: "lanes_copy", layerType: "points" };
    const layers = await applyComputeBlocks([ROADS], [PASS, written], failures);
    expect(failures).toEqual([]);
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(2);
    expect(computeRuns.gpgpu.mock.calls[1][0]).toEqual(dispatchOf(written));
    // The second dispatch is the pass that writes the new table: its result is that table.
    expect(layers.map((l) => [l.name, l.type])).toEqual([["input_0", "roads"], ["lanes_copy", "points"]]);
  });

  test("a render pass runs", async () => {
    const failures: string[] = [];
    const render = {
      type: "render", outputTableName: "views", layers: [{ id: "lanes", dataRef: "input_0", type: "roads" }],
      viewpoints: { dataRef: "input_0" }, aggregation: { type: "classes" },
    };
    const layers = await applyComputeBlocks([ROADS], [render], failures);
    expect(failures).toEqual([]);
    expect(computeRuns.render).toHaveBeenCalledTimes(1);
    expect(computeRuns.render.mock.calls[0][0]).toEqual(expect.objectContaining({
      layers: [expect.objectContaining({ id: "lanes", type: "roads", collection: ROADS.geojson })],
      viewpoints: expect.objectContaining({ collection: ROADS.geojson }),
      aggregation: render.aggregation,
    }));
    expect(layers.map((l) => [l.name, l.type])).toEqual([["input_0", "roads"], ["views", "roads"]]);
  });
});

describe("loadSpecLayers", () => {
  test.each([
    [
      "a join written with tableJoinName",
      { data: [{ type: "join", dataRef: "a", tableJoinName: "b" }] },
      'This spec uses "tableJoinName" at data[0], which autk-grammar 5 renamed to "joinDataRef".',
    ],
    [
      "a geotiff source",
      { data: [{ type: "geotiff", geotiffFileUrl: "lst.tif", outputTableName: "lst" }] },
      "This spec uses a geotiff source at data[0], which Curio does not run yet.",
    ],
    [
      "a source in a workspace",
      { data: [{ type: "csv", csvFileUrl: "a.csv", outputTableName: "a", workspace: "east" }] },
      'This spec uses "workspace" at data[0], which Curio does not run yet.',
    ],
  ])("%s fails the load, named, and makes no database", async (_what, spec, said) => {
    await expect(loadSpecLayers(spec)).rejects.toThrow(said);
    expect(mockAutkDb).not.toHaveBeenCalled();
  });
});
