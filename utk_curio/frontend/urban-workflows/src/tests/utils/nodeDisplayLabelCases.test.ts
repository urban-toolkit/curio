/**
 * The cases in utils/nodeDisplayLabel.cases.json, run through the canvas's own
 * rule. backend/tests/test_execution/test_node_names.py runs the same file
 * through execution/node_names.py, so a run on the server, a save and a node's
 * play give a node the name its header shows (#775).
 */
import fs from "fs";
import path from "path";

import { nodeDisplayLabel } from "../../utils/nodeDisplayLabel";

interface LabelCase {
  name: string;
  nodeType: string;
  customLabel?: string;
  templateLabel?: string;
  label: string;
}

const CASES: LabelCase[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../utils/nodeDisplayLabel.cases.json"), "utf8"),
).cases;

describe.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
  test("names the node as expected", () => {
    expect(nodeDisplayLabel(c.nodeType, c.customLabel, c.templateLabel)).toBe(c.label);
  });
});

test("no name carries a version suffix", () => {
  for (const c of CASES) {
    expect(nodeDisplayLabel(c.nodeType, c.customLabel, c.templateLabel)).not.toMatch(/@\d+$/);
  }
});
