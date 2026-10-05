/**
 * The cases in utils/saveOutputDataset.cases.json, run through the canvas's
 * own rules. backend/tests/test_execution/test_save_policy.py runs the same
 * file through execution/save_policy.py, so a run on the server saves the
 * outputs the canvas would.
 */
import fs from "fs";
import path from "path";

import { CURIO_UNIVERSAL_NODE_TYPE } from "../../constants";
import {
  buildSaveableLiveOutputs,
  shouldSaveOutputOnRun,
} from "../../utils/saveOutputDataset";

interface SaveCase {
  name: string;
  node: { nodeType: string; saveOutputDataset?: boolean; datasetSource?: boolean };
  defaultSave: boolean;
  dashboardSource: boolean;
  onRun: boolean;
  recorded: boolean;
}

const CASES: SaveCase[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../utils/saveOutputDataset.cases.json"), "utf8"),
).cases;

/** The case's node as the canvas holds it. */
function canvasNode(c: SaveCase) {
  const data: any = { nodeId: "n", nodeType: c.node.nodeType };
  if (c.node.saveOutputDataset !== undefined) data.saveOutputDataset = c.node.saveOutputDataset;
  if (c.node.datasetSource) data.datasetSource = { datasetId: "data.curio.example" };
  return { id: "n", type: CURIO_UNIVERSAL_NODE_TYPE, data };
}

describe.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
  test("a run installs the output when expected", () => {
    expect(shouldSaveOutputOnRun(canvasNode(c).data, c.defaultSave, c.dashboardSource)).toBe(c.onRun);
  });

  test("a save records the output when expected", () => {
    const refs = buildSaveableLiveOutputs(
      [{ nodeId: "n", output: { path: "1790000000000_deadbeef", dataType: "dataframe" } }],
      [canvasNode(c)],
      c.defaultSave,
      c.dashboardSource ? new Set(["n"]) : null,
    );
    expect((refs ?? []).some((r) => r.node_id === "n")).toBe(c.recorded);
  });
});
