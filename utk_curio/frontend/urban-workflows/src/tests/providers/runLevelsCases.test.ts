/**
 * The cases in providers/flow/runLevels.cases.json, run through Run All's own
 * computeTopologicalLevels. backend/tests/test_runs/test_run_plan.py runs the
 * same file through execution/run_plan.topological_levels, so a run on the
 * server goes in the order Run All does.
 */
import fs from "fs";
import path from "path";

import { computeTopologicalLevels } from "../../providers/flow/runLevels";

interface LevelCase {
  name: string;
  nodes: string[];
  edges: Array<{ id: string; source: string; target: string; type?: string; sourceHandle?: string; targetHandle?: string }>;
  levels: string[][];
}

const CASES: LevelCase[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../providers/flow/runLevels.cases.json"), "utf8"),
).cases;

test.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
  const nodes = c.nodes.map((id) => ({ id, position: { x: 0, y: 0 }, data: {} }));
  expect(computeTopologicalLevels(nodes as any, c.edges as any)).toEqual(c.levels);
});
