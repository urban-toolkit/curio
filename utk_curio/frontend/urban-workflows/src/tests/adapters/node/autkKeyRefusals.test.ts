/**
 * The paths that run part of an Autark document refuse a key autk-grammar 5
 * renamed, or one a node does not run yet, as the node's run does
 * (contracts/autkGrammar's autkKeyProblem): the compute of a compute-only node
 * (applyComputeBlocks) and the browser's loader of a data section
 * (loadSpecLayers). Neither runs any of it: no pass is dispatched and no
 * database is made.
 */
const mockRunCompute = jest.fn();
const mockAutkDb = jest.fn();

jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
jest.mock("@urban-toolkit/autk-grammar", () => ({ runCompute: (...a: any[]) => mockRunCompute(...a) }), { virtual: true });
jest.mock("@urban-toolkit/autk-compute", () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
jest.mock("@urban-toolkit/autk-db", () => ({
  AutkDb: function AutkDb(...a: any[]) { return mockAutkDb(...a); },
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
}), { virtual: true });

import { applyComputeBlocks } from "../../../adapters/node/autkComputeBlocks";
import { loadSpecLayers } from "../../../adapters/node/autkLayerMaterialize";

const ROADS = {
  name: "input_0",
  type: "roads",
  geojson: {
    type: "FeatureCollection" as const,
    features: [{ type: "Feature" as const, properties: { lanes: 2 }, geometry: { type: "Point" as const, coordinates: [0, 0] } }],
  },
};
const PASS = { dataRef: "input_0", attributes: { x: "lanes" }, wgslFunction: "return x;", outputColumnName: "y" };

beforeEach(() => {
  mockRunCompute.mockReset();
  mockAutkDb.mockReset();
});

describe("applyComputeBlocks", () => {
  test.each([
    [
      "a pass written with wglsFunction",
      [{ ...PASS, wgslFunction: undefined, wglsFunction: "return x;" }],
      'This spec uses "wglsFunction" at compute[0], which autk-grammar 5 renamed to "wgslFunction".',
    ],
    [
      "a render pass",
      [{ type: "render", outputTableName: "views", layers: [], viewpoints: { dataRef: "input_0" }, aggregation: { type: "classes" } }],
      "This spec uses a render pass at compute[0], which Curio does not run yet.",
    ],
  ])("%s is a failure, named, and no pass runs", async (_what, passes, said) => {
    const failures: string[] = [];
    const layers = await applyComputeBlocks([ROADS], passes as any[], failures);
    expect(failures).toEqual([said]);
    expect(layers).toEqual([ROADS]);
    expect(mockRunCompute).not.toHaveBeenCalled();
  });

  test("guard: a pass of autk-grammar 5's keys runs", async () => {
    mockRunCompute.mockResolvedValue(ROADS.geojson);
    const failures: string[] = [];
    await applyComputeBlocks([ROADS], [PASS], failures);
    expect(failures).toEqual([]);
    expect(mockRunCompute).toHaveBeenCalledTimes(1);
    expect(mockRunCompute.mock.calls[0][0]).toBe(PASS);
  });

  test("a pass that writes a new table, with its type, runs", async () => {
    mockRunCompute.mockResolvedValue(ROADS.geojson);
    const failures: string[] = [];
    const written = { ...PASS, outputTableName: "lanes_copy", layerType: "points" };
    await applyComputeBlocks([ROADS], [PASS, written], failures);
    expect(failures).toEqual([]);
    expect(mockRunCompute).toHaveBeenCalledTimes(2);
    expect(mockRunCompute.mock.calls[1][0]).toBe(written);
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
  ])("%s fails the load, named, and makes no database", async (_what, spec, said) => {
    await expect(loadSpecLayers(spec)).rejects.toThrow(said);
    expect(mockAutkDb).not.toHaveBeenCalled();
  });
});
