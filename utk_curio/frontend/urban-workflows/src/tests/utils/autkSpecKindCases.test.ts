/**
 * The cases in utils/autkSpecKind.cases.json, run through the canvas's own
 * classifyAutkSpecString, and through isPassThroughNode, the canvas's twin of
 * the role a run on the server gives an Autark node.
 * backend/tests/test_runs/test_autk_spec_kind.py runs the same file through
 * execution/autk_spec_kind and run_plan.node_role, so a run on the server sorts
 * an Autark node by the canvas's rule: a document that only loads data runs on
 * the server, one that only draws its input is forwarded, and the rest wait for
 * the browser, a node that draws and also loads or computes among them.
 */
import fs from "fs";
import path from "path";

import { NodeType } from "../../constants";
import { isPassThroughNode } from "../../utils/dashboardLayout";
import { classifyAutkSpecString, type AutkSpecKind } from "../../utils/autkSpecKind";

interface KindCase {
  name: string;
  spec: string;
  kind: AutkSpecKind;
  /** What a run on the server does with an Autark node of this document (run_plan.node_role). */
  role: "run" | "forward" | "browser";
}

const CASES: KindCase[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../utils/autkSpecKind.cases.json"), "utf8"),
).cases;

/** An Autark node of the canvas holding *spec*, as the dashboard walk reads it. */
const autarkNode = (spec: string) => ({
  id: "n",
  type: "__curioUniversalNode",
  data: { nodeId: "n", nodeType: NodeType.AUTK_GRAMMAR, code: spec },
});

test.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
  expect(classifyAutkSpecString(c.spec)).toBe(c.kind);
});

test.each(CASES.map((c) => [c.name, c] as const))("%s: its node has the role a run gives it", (_name, c) => {
  // Only a node a run forwards passes its input through, as the dashboard
  // walk and a scenario's saved outputs read it; only one that only loads
  // data runs on the server.
  expect(isPassThroughNode(autarkNode(c.spec))).toBe(c.role === "forward");
  expect(classifyAutkSpecString(c.spec) === "data").toBe(c.role === "run");
});
