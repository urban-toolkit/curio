/**
 * The dataflows a catalog's Remove names: those whose nodes use the item in
 * their code alone, the open one read from its canvas and the account's others
 * from the usage read. Written once (`codeOnlyDataflows`), for the Data
 * Catalog's Remove and the Model Catalog's.
 *
 * Code main lacks is reached through `require`, so main fails test by test.
 */
import fs from "fs";
import path from "path";

const codeOnlyDataflows = (...args: unknown[]): Promise<string[]> =>
  require("../../services/codeOnlyUsage").codeOnlyDataflows(...args);

describe("codeOnlyDataflows", () => {
  test("names this dataflow from its canvas and the account's others from their usage rows, by name", async () => {
    const names = await codeOnlyDataflows(
      { id: "p1", name: "street photos", inCodeOnly: true },
      async () => [
        // This dataflow as last saved: its canvas answers for it.
        { dataflowId: "p1", dataflowName: "Street photos, as saved", nodeCount: 1, codeOnly: false },
        { dataflowId: "p2", dataflowName: "Crosswalks", nodeCount: 1, codeOnly: true },
        { dataflowId: "p3", dataflowName: "Keeps it", nodeCount: 1, codeOnly: false },
        { dataflowId: "p4", dataflowName: null, nodeCount: 2, codeOnly: true },
      ],
    );
    expect(names).toEqual(["Crosswalks", "street photos", "Untitled dataflow"]);
  });

  test("never names this dataflow from its saved row", async () => {
    const names = await codeOnlyDataflows(
      { id: "p1", name: "Street photos", inCodeOnly: false },
      async () => [{ dataflowId: "p1", dataflowName: "Street photos", nodeCount: 1, codeOnly: true }],
    );
    expect(names).toEqual([]);
  });

  test("calls a dataflow with no name Untitled dataflow", async () => {
    expect(await codeOnlyDataflows({ id: null, name: "", inCodeOnly: true }, async () => [])).toEqual([
      "Untitled dataflow",
    ]);
  });

  test("names this dataflow alone when the usage read fails", async () => {
    const names = await codeOnlyDataflows({ id: "p1", name: "Street photos", inCodeOnly: true }, async () => {
      throw new Error("offline");
    });
    expect(names).toEqual(["Street photos"]);
  });
});

describe("both catalogs' Remove name them through codeOnlyDataflows", () => {
  const SRC = path.resolve(__dirname, "../..");

  test.each([
    ["the Data Catalog drawer", "components/datasets/catalog/useDatasetCatalogDrawer.ts"],
    ["the Model Catalog drawer", "components/packages/publishing/NodeCatalogDrawer.tsx"],
  ])("%s", (_name, rel) => {
    const source = fs.readFileSync(path.join(SRC, rel), "utf8");
    expect(source).toContain("codeOnlyDataflows(");
    // The open dataflow's saved row is dropped in the shared code, not here.
    expect(source).not.toMatch(/dataflowId\s*!==/);
  });
});
