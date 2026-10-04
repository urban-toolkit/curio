/**
 * What a spec keeps of `dataflow.scenarios` (#662). The cases live in
 * `utils/scenarios/scenarios.cases.json`, which
 * `utk_curio/backend/tests/test_projects/test_scenarios.py` reads too: the
 * canvas and the backend keep the same scenarios.
 *
 * Then the writer: `generateTrill` writes them when it is handed them, a
 * version snapshot and an agent's view only when there are some.
 */
jest.mock("../../registry/nodeRegistry", () => ({ getPaletteNodeTypes: () => [] }));

import cases from "../../utils/scenarios/scenarios.cases.json";
import { normalizeScenarios, type Scenario } from "../../utils/scenarios/scenarioModel";
import { TrillGenerator } from "../../TrillGenerator";
import { composeAgentRunContext, type AgentAttachment } from "../../services/agents";

type Case = { name: string; nodes: string[]; scenarios: unknown; expected: Scenario[] };

describe("the shared scenario cases", () => {
  test.each((cases.cases as Case[]).map((c) => [c.name, c]))("%s", (_name, c) => {
    expect(normalizeScenarios(c.scenarios, c.nodes)).toEqual(c.expected);
  });
});

const node = (id: string) => ({ id, type: "CODE", position: { x: 0, y: 0 }, data: { nodeId: id, nodeType: "CODE" } });
const NODES = [node("a"), node("b")];
const BASELINE: Scenario = { id: "s1", name: "Baseline", color: "#2a9d8f", nodes: ["a"] };
const TALL: Scenario = { id: "s2", name: "Twice as tall", color: "#e76f51", nodes: ["b", "deleted"] };

describe("generateTrill and scenarios", () => {
  beforeEach(() => TrillGenerator.reset());

  test("writes them, keeping only the members it writes as nodes", () => {
    const spec = TrillGenerator.generateTrill(NODES, [], "wf", "", [], "", [], {}, [BASELINE, TALL]);
    expect(spec.dataflow.scenarios).toEqual([BASELINE, { ...TALL, nodes: ["b"] }]);
  });

  test("a scenario whose nodes are all gone keeps its name and color", () => {
    const spec = TrillGenerator.generateTrill([node("a")], [], "wf", "", [], "", [], {}, [TALL]);
    expect(spec.dataflow.scenarios).toEqual([{ ...TALL, nodes: [] }]);
  });

  test("an empty list is written, so a save clears them", () => {
    const spec = TrillGenerator.generateTrill(NODES, [], "wf", "", [], "", [], {}, []);
    expect(spec.dataflow.scenarios).toEqual([]);
  });

  test("left out, no key is written, so the server keeps what it has", () => {
    const spec = TrillGenerator.generateTrill(NODES, [], "wf");
    expect("scenarios" in spec.dataflow).toBe(false);
  });

  test("a version snapshot carries them only when there are some", () => {
    TrillGenerator.addNewVersionProvenance(NODES, [], "wf", "", "none yet");
    TrillGenerator.scenarios = [BASELINE];
    TrillGenerator.addNewVersionProvenance(NODES, [], "wf", "", "one");
    const [first, second] = Object.values(TrillGenerator.list_of_trills) as any[];
    expect("scenarios" in first.dataflow).toBe(false);
    expect(second.dataflow.scenarios).toEqual([BASELINE]);
  });

  test("reset clears them", () => {
    TrillGenerator.scenarios = [BASELINE];
    TrillGenerator.reset();
    expect(TrillGenerator.scenarios).toEqual([]);
  });
});

describe("an agent's view of the dataflow", () => {
  const reader: AgentAttachment = {
    attachmentId: "a1",
    coord: "agent.dataflow-reader@1.0.0",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    name: "X",
    category: "node",
    hooks: [],
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    reads: ["dataflowContext"],
  };

  const trillOf = (context: string | null) => JSON.parse(String(context).replace(/^Current Trill: /, ""));

  test("carries the scenarios", () => {
    const context = composeAgentRunContext(reader, {
      nodes: NODES, edges: [], workflowName: "wf", workflowGoal: "", scenarios: [BASELINE],
    });
    expect(trillOf(context).dataflow.scenarios).toEqual([BASELINE]);
  });

  test("has no scenarios key when there are none", () => {
    const context = composeAgentRunContext(reader, {
      nodes: NODES, edges: [], workflowName: "wf", workflowGoal: "", scenarios: [],
    });
    expect("scenarios" in trillOf(context).dataflow).toBe(false);
  });
});
