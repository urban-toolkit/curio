/**
 * The nodes around a scenario (#662), from one table of cases,
 * `utils/scenarios/scenarioNeighbors.cases.json`, which the backend reads too
 * (`utk_curio/backend/tests/test_scenario_catalog/test_parts.py`): a save
 * stores what the canvas would find.
 */
import cases from "../../utils/scenarios/scenarioNeighbors.cases.json";
import { scenarioNeighbors } from "../../utils/scenarios/scenarioParts";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

type SpecNode = { id: string; type: string; content?: string; metadata?: { widgets?: unknown } };
type SpecEdge = { source: string; target: string; sourceHandle?: string; targetHandle?: string };
type Case = {
  name: string;
  nodes: SpecNode[];
  edges: SpecEdge[];
  scenarios: { id: string; nodes: string[] }[];
  scenario: string;
  expected: { upstream: string[]; downstream: string[] };
};

const canvasNode = (n: SpecNode) => ({
  id: n.id,
  type: "__curioUniversalNode",
  position: { x: 0, y: 0 },
  data: { nodeId: n.id, nodeType: n.type, code: n.content ?? "", widgets: n.metadata?.widgets },
});

describe("the shared scenario neighbors cases", () => {
  test.each((cases.cases as Case[]).map((c) => [c.name, c]))("%s", (_name, c) => {
    const scenarios: Scenario[] = c.scenarios.map((s) => ({ ...s, name: s.id, color: "#2a9d8f" }));
    const scenario = scenarios.find((s) => s.id === c.scenario)!;
    expect(scenarioNeighbors(scenario, scenarios, c.nodes.map(canvasNode), c.edges)).toEqual(c.expected);
  });
});
