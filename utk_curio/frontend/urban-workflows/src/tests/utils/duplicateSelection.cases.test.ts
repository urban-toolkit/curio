/**
 * Duplicate selection (#662) from one table of cases,
 * `utils/scenarios/duplicateSelection.cases.json`. A Dataflow Builder plan's
 * duplicate reads the same table through the backend's twin
 * (`utk_curio/backend/tests/test_scenario_catalog/test_duplicate.py`), so a
 * plan copies a selection the way the canvas's Duplicate selection does.
 */
import cases from "../../utils/scenarios/duplicateSelection.cases.json";
import { duplicateSelection, type SpecEdge, type SpecNode } from "../../utils/scenarios/duplicateSelection";

type Case = {
  name: string;
  nodes: SpecNode[];
  edges: SpecEdge[];
  selected: string[];
  expected: { ids: [string, string][]; nodes: SpecNode[]; edges: SpecEdge[] };
};

function ids() {
  let n = 0;
  return () => `copy-${++n}`;
}

describe("the shared duplicate selection cases", () => {
  test.each((cases.cases as unknown as Case[]).map((c) => [c.name, c]))("%s", (_name, c) => {
    const copy = duplicateSelection({ nodes: c.nodes, edges: c.edges }, c.selected, {
      newId: ids(),
      offset: { x: 0, y: 400 },
    });
    expect([...copy.ids.entries()]).toEqual(c.expected.ids);
    expect(copy.nodes).toEqual(c.expected.nodes);
    expect(copy.edges).toEqual(c.expected.edges);
  });
});
