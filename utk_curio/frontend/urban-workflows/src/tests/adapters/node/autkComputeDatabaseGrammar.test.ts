/**
 * What a compute step that runs on a database of its own reads of
 * autk-grammar (adapters/node/autkComputeDatabase.ts), pinned on the grammar
 * build the app bundles. Such a step runs its document through the adapters
 * and caches an `AutkGrammar` wires for itself, which the grammar keeps in
 * fields of its own rather than offers to hosts: its `dataAdapter`, its
 * `computeAdapter` and its compute caches, `_computeCache` and
 * `_computeTypes`. A grammar release that names them otherwise, or wires them
 * apart, fails here, where the step would otherwise only say it cannot run
 * (`COMPUTE_DATABASE_MISSING`) on the GPU job.
 *
 * - The data adapter sets up workspaces and loads a source; the compute
 *   adapter runs a pass.
 * - The compute adapter keeps a pass's result, and the type of a table a pass
 *   writes under a name of its own, in those two caches.
 * - The data adapter takes a table a source writes, a drop here, out of them,
 *   so the step reads such a table from autk-db.
 */
jest.mock("@urban-toolkit/autk-grammar", () => require("../../_support/autkComputeStandIns").grammarBuild(), { virtual: true });
jest.mock("@urban-toolkit/autk-compute", () => require("../../_support/autkComputeStandIns").autkComputeModule, { virtual: true });
jest.mock("@urban-toolkit/autk-core", () => require("../../_support/autkComputeStandIns").autkCoreBuild(), { virtual: true });
jest.mock("@urban-toolkit/autk-map", () => require("../../_support/autkComputeStandIns").autkMapModule, { virtual: true });
jest.mock("@urban-toolkit/autk-plot", () => require("../../_support/autkComputeStandIns").autkPlotModule, { virtual: true });
jest.mock("@urban-toolkit/autk-db", () => ({
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  DEFAULT_WORKSPACE_NAME: "autk",
  isVectorTable: () => true,
  isRenderableTable: () => true,
}), { virtual: true });

import { AutkGrammar } from "@urban-toolkit/autk-grammar";

/** A square of side 10 at *x*. */
const square = (x: number) => ({
  type: "Feature",
  geometry: { type: "Polygon", coordinates: [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]] },
  properties: { at: x },
});

/** A database the adapters can run on: it holds the tables *held* lists, by name, in the default workspace. */
function database(held: string[]) {
  let workspace = "autk";
  const tables = new Set(held);
  return {
    getCurrentWorkspace: () => workspace,
    setWorkspace: jest.fn(async (name: string) => {
      workspace = name;
    }),
    getWorkspaceConfiguration: () => ({ coordinateFormat: "EPSG:3395" }),
    getTablesMetadata: () => [...tables].map((name) => ({ name, type: "polygons", source: "geojson", columns: [] })),
    getLayer: jest.fn(async (name: string) => {
      throw new Error(`Table ${name} not found.`);
    }),
    removeLayer: jest.fn(async (name: string) => {
      tables.delete(name);
    }),
  };
}

describe("an AutkGrammar keeps the adapters and caches a compute step runs on", () => {
  test("its data adapter and compute adapter, and its compute caches as maps", () => {
    const grammar: any = new (AutkGrammar as any)({});
    expect(typeof grammar.dataAdapter?.resolveWorkspaces).toBe("function");
    expect(typeof grammar.dataAdapter?.resolveSource).toBe("function");
    expect(typeof grammar.computeAdapter?.resolveCompute).toBe("function");
    expect(grammar._computeCache).toBeInstanceOf(Map);
    expect(grammar._computeTypes).toBeInstanceOf(Map);
  });

  test("its compute adapter keeps a pass's result and its table's type in those caches", async () => {
    const grammar: any = new (AutkGrammar as any)({});
    // A table an earlier pass wrote, which a pass reads from the cache first.
    grammar._computeCache.set("squares", { type: "FeatureCollection", features: [square(0), square(10), square(40)] });
    await grammar.computeAdapter.resolveCompute(database([]), {
      type: "clusters", dataRef: "squares", outputColumnName: "block", outputTableName: "blocks", layerType: "polygons",
    });
    const blocks = grammar._computeCache.get("blocks");
    expect(blocks?.features.map((feature: any) => feature.properties.compute.block)).toEqual([0, 0, 1]);
    expect(grammar._computeTypes.get("blocks")).toBe("polygons");
  });

  test("its data adapter takes a table a source writes out of those caches", async () => {
    const grammar: any = new (AutkGrammar as any)({});
    grammar._computeCache.set("blocks", { type: "FeatureCollection", features: [square(0)] });
    grammar._computeTypes.set("blocks", "polygons");
    grammar._computeCache.set("kept", { type: "FeatureCollection", features: [square(0)] });
    await grammar.dataAdapter.resolveSource(database(["blocks"]), { type: "drop", dataRef: "blocks", after: "compute" });
    expect(grammar._computeCache.has("blocks")).toBe(false);
    expect(grammar._computeTypes.has("blocks")).toBe(false);
    expect(grammar._computeCache.has("kept")).toBe(true);
  });
});
