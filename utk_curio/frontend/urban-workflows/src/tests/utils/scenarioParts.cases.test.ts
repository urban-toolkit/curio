/**
 * A scenario's levers, fixed context and outcomes, and what stands for a
 * node's saved output (#662), from one table of cases,
 * `utils/scenarios/scenarioParts.cases.json`. The Scenario Catalog reads the
 * same table (`utk_curio/backend/tests/test_scenario_catalog/test_parts.py`),
 * so the catalog lists a scenario the way its canvas shows it.
 *
 * The cases are written as a saved spec holds nodes; here each becomes the
 * canvas node a load makes of it.
 */
import cases from "../../utils/scenarios/scenarioParts.cases.json";
import { savedSourcesOf, scenarioParts } from "../../utils/scenarios/scenarioParts";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

type SpecNode = { id: string; type: string; content?: string; metadata?: { widgets?: unknown } };
type SpecEdge = { source: string; target: string; sourceHandle?: string; targetHandle?: string; type?: string };
type Case = {
  name: string;
  nodes: SpecNode[];
  edges: SpecEdge[];
  scenario: string[];
  expected: { levers: string[]; context: string[]; outcomes: string[] };
  savedSources?: Record<string, string[]>;
};

const canvasNode = (n: SpecNode) => ({
  id: n.id,
  type: "__curioUniversalNode",
  position: { x: 0, y: 0 },
  data: { nodeId: n.id, nodeType: n.type, code: n.content ?? "", widgets: n.metadata?.widgets },
});

const scenario = (nodes: string[]): Scenario => ({ id: "s1", name: "Baseline", color: "#2a9d8f", nodes });

describe("the shared scenario parts cases", () => {
  test.each((cases.cases as Case[]).map((c) => [c.name, c]))("%s", (_name, c) => {
    const nodes = c.nodes.map(canvasNode);
    expect(scenarioParts(scenario(c.scenario), nodes, c.edges)).toEqual(c.expected);
    for (const [id, expected] of Object.entries(c.savedSources ?? {})) {
      expect([id, savedSourcesOf(id, nodes, c.edges)]).toEqual([id, expected]);
    }
  });
});
