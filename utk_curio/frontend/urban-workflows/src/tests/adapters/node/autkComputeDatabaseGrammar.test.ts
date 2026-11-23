/**
 * What a compute step that runs on a database of its own reads of
 * autk-grammar (adapters/node/autkComputeDatabase.ts), pinned on the grammar
 * build the app bundles: the steps of a run the grammar gives a host
 * (`createComputeSteps`, autk-grammar 5.6.0), each on the database the step
 * hands it. A grammar release that takes them away, or wires them apart,
 * fails here, where the step would otherwise only say it cannot run
 * (`COMPUTE_DATABASE_MISSING`) on the GPU job.
 *
 * - The steps set up workspaces, load a source and run a pass.
 * - `computed` gives a pass's result, and the type of a table a pass writes
 *   under a name of its own; a later pass reads the table there.
 * - A source that writes a table, a drop here, takes it out of `computed`, so
 *   the step reads such a table from autk-db.
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

import { createComputeSteps } from "@urban-toolkit/autk-grammar";

/** A square of side 10 at *x*. */
const square = (x: number) => ({
  type: "Feature",
  geometry: { type: "Polygon", coordinates: [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]] },
  properties: { at: x },
});

/** Three squares: the first two share an edge, so a clusters pass puts them in one cluster, and the third in another. */
const squares = () => ({ type: "FeatureCollection", features: [square(0), square(10), square(40)] });

/**
 * A database the steps can run on: it holds the tables *layers* names, by
 * name, in the default workspace, each exported as *layers* gives it.
 */
function database(layers: Record<string, any>) {
  let workspace = "autk";
  const tables = new Set(Object.keys(layers));
  return {
    getCurrentWorkspace: () => workspace,
    setWorkspace: jest.fn(async (name: string) => {
      workspace = name;
    }),
    getWorkspaceConfiguration: () => ({ coordinateFormat: "EPSG:3395" }),
    getTablesMetadata: () => [...tables].map((name) => ({ name, type: "polygons", source: "geojson", columns: [] })),
    getLayer: jest.fn(async (name: string) => {
      if (!tables.has(name)) throw new Error(`Table ${name} not found.`);
      return layers[name];
    }),
    removeLayer: jest.fn(async (name: string) => {
      tables.delete(name);
    }),
  };
}

/** A clusters pass over *dataRef*, as a compute step hands it on. */
const clusters = (fields: Record<string, unknown>): any => ({ type: "clusters", dataRef: "squares", outputColumnName: "block", ...fields });

describe("autk-grammar gives a host the steps of a run a compute step runs on its own database", () => {
  test("its steps set up workspaces, load a source and run a pass, and give each pass's result", () => {
    const steps: any = createComputeSteps();
    expect(typeof steps.resolveWorkspaces).toBe("function");
    expect(typeof steps.resolveSource).toBe("function");
    expect(typeof steps.resolveCompute).toBe("function");
    expect(typeof steps.computed).toBe("function");
  });

  test("computed gives a pass's result and the type of the table it writes, and a later pass reads the table there", async () => {
    const steps = createComputeSteps();
    const db: any = database({ squares: squares() });
    await steps.resolveCompute(db, clusters({ outputTableName: "blocks", layerType: "polygons" }));
    const blocks = steps.computed("blocks");
    expect(blocks?.collection.features.map((feature: any) => feature.properties.compute.block)).toEqual([0, 0, 1]);
    expect(blocks?.layerType).toBe("polygons");
    // The database holds no table of that name: a later pass reads the first one's result.
    await steps.resolveCompute(db, clusters({ dataRef: "blocks", outputColumnName: "again" }));
    expect(db.getLayer).not.toHaveBeenCalledWith("blocks");
    expect(steps.computed("blocks")?.collection.features.map((feature: any) => feature.properties.compute.again)).toEqual([0, 0, 1]);
  });

  test("a source that writes a table takes it out of what computed gives, and leaves the others", async () => {
    const steps = createComputeSteps();
    // The database holds the squares and the blocks a pass wrote back.
    const db: any = database({ squares: squares(), blocks: squares() });
    await steps.resolveCompute(db, clusters({ outputTableName: "blocks", layerType: "polygons" }));
    await steps.resolveCompute(db, clusters({ outputTableName: "kept" }));
    expect(steps.computed("blocks")).toBeDefined();
    await steps.resolveSource(db, { type: "drop", dataRef: "blocks", after: "compute" } as any);
    expect(db.removeLayer).toHaveBeenCalledWith("blocks");
    expect(steps.computed("blocks")).toBeUndefined();
    expect(steps.computed("kept")).toBeDefined();
  });
});
