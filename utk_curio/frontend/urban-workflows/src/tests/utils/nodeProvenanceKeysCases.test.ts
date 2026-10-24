/**
 * The cases in utils/nodeProvenanceKeys.cases.json, run through the load's own
 * rule. backend/tests/test_projects/test_node_provenance_keys.py runs the same
 * file through projects/node_provenance.py, which the agents' node.history.read
 * keys a saved dataflow's node histories with, so an agent reads the history a
 * node's Provenance drawer lists.
 */
import fs from "fs";
import path from "path";

import { rekeyNodeProvenance } from "../../utils/nodeProvenanceKeys";
import type { NodeExecRecord } from "../../providers/ProvenanceProvider";

interface KeysCase {
  name: string;
  saved: Record<string, NodeExecRecord[]>;
  nodeIds: string[];
  keyed: Record<string, NodeExecRecord[]>;
}

const CASES: KeysCase[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../utils/nodeProvenanceKeys.cases.json"), "utf8"),
).cases;

test("the cases cover a move, a merge, a node id with a dash and a value that is no list", () => {
  expect(CASES.length).toBeGreaterThanOrEqual(8);
});

describe.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
  test("a load keys the saved histories as the case says", () => {
    expect(rekeyNodeProvenance(c.saved, c.nodeIds)).toEqual(c.keyed);
  });
});
