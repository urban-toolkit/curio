/**
 * A dataflow's scenario sets, from one table of cases,
 * `utils/scenarios/scenarioSets.cases.json`, which the backend reads too
 * (`utk_curio/backend/tests/test_projects/test_scenario_sets.py`): each
 * scenario's context and outcomes, inferred up and down its edges or kept as
 * finalized, and the set it is grouped into.
 */
import cases from "../../utils/scenarios/scenarioSets.cases.json";
import { normalizeScenarios } from "../../utils/scenarios/scenarioModel";
import { normalizeScenarioSets, setMembership } from "../../utils/scenarios/scenarioSets";

type Case = {
  name: string;
  dataflowName?: string;
  nodes: string[];
  edges: { source: string; target: string; type?: string; sourceHandle?: string; targetHandle?: string }[];
  sets?: unknown;
  scenarios: unknown[];
  expected: { scenarioSets: unknown; scenarios: unknown };
};

describe("the shared scenario sets cases", () => {
  test.each((cases.cases as Case[]).map((c) => [c.name, c]))("%s", (_name, c) => {
    const kept = normalizeScenarios(c.scenarios, c.nodes);
    const got = normalizeScenarioSets(kept, c.sets, c.nodes, c.edges, c.dataflowName);
    expect({ scenarioSets: got.sets, scenarios: got.scenarios }).toEqual(c.expected);
  });

  test("membership lists each node's scenarios in the set's order", () => {
    const kept = (cases.cases[0] as unknown as Case).expected.scenarios as ReturnType<typeof normalizeScenarios>;
    const member = setMembership(kept, kept[0].set!);
    expect(member.scenarios).toEqual(["existing", "towers", "cap"]);
    expect(member.context.around).toEqual(["towers", "cap"]);
    expect(member.outcomes.changeT).toEqual(["existing", "towers"]);
  });
});
