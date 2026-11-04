/**
 * A scenario's parts by role (#662): its own nodes, its shared context and
 * shared outcomes, its boundary, what saves its output because of the
 * scenarios, and what stands for a node's saved output, from one table of
 * cases, `utils/scenarios/scenarioParts.cases.json`. The Scenario Catalog
 * reads the same table (`utk_curio/backend/tests/test_scenario_catalog/test_parts.py`),
 * so the catalog lists a scenario the way its canvas shows it.
 *
 * The cases are written as a saved spec holds nodes; here each becomes the
 * canvas node a load makes of it. A case's chart is known to the canvas as its
 * installed package registers it; the catalog reads its shipped manifest.
 */
import cases from "../../utils/scenarios/scenarioParts.cases.json";
import { savedSourcesOf, scenarioParts, scenarioSourceNodeIds } from "../../utils/scenarios/scenarioParts";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import { clearVegaLiteTemplate, registerVegaLiteTemplate } from "../_support/vegaLiteTemplate";

beforeAll(() => registerVegaLiteTemplate());
afterAll(() => clearVegaLiteTemplate());

type SpecNode = { id: string; type: string; content?: string; metadata?: { widgets?: unknown } };
type SpecEdge = { source: string; target: string; sourceHandle?: string; targetHandle?: string; type?: string };
type Parts = { nodes: string[]; context: string[]; outcomes: string[]; boundary: string[] };
type Case = {
  name: string;
  nodes: SpecNode[];
  edges: SpecEdge[];
  scenarios: { id: string; nodes: string[]; context?: string[]; outcomes?: string[] }[];
  expected: Record<string, Parts>;
  saves: string[];
  savedSources?: Record<string, string[]>;
};

const canvasNode = (n: SpecNode) => ({
  id: n.id,
  type: "__curioUniversalNode",
  position: { x: 0, y: 0 },
  data: { nodeId: n.id, nodeType: n.type, code: n.content ?? "", widgets: n.metadata?.widgets },
});

const scenariosOf = (c: Case): Scenario[] => c.scenarios.map((s) => ({ name: s.id, color: "#2a9d8f", ...s }));

describe("the shared scenario parts cases", () => {
  test.each((cases.cases as Case[]).map((c) => [c.name, c]))("%s", (_name, c) => {
    const nodes = c.nodes.map(canvasNode);
    const scenarios = scenariosOf(c);
    for (const scenario of scenarios) {
      expect([scenario.id, scenarioParts(scenario, nodes, c.edges, scenarios)]).toEqual([
        scenario.id,
        c.expected[scenario.id],
      ]);
    }
    expect([...scenarioSourceNodeIds(nodes, c.edges, scenarios)].sort()).toEqual(c.saves);
    for (const [id, expected] of Object.entries(c.savedSources ?? {})) {
      expect([id, savedSourcesOf(id, nodes, c.edges)]).toEqual([id, expected]);
    }
  });
});
