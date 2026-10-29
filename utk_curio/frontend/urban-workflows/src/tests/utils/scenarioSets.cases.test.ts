/**
 * A dataflow's scenario sets, from one table of cases,
 * `utils/scenarios/scenarioSets.cases.json`, which the backend reads too
 * (`utk_curio/backend/tests/test_projects/test_scenario_sets.py`): each
 * scenario's context and outcomes, inferred up and down its edges or kept as
 * finalized, and the set it is grouped into.
 */
import cases from "../../utils/scenarios/scenarioSets.cases.json";
import { normalizeScenarios } from "../../utils/scenarios/scenarioModel";
import { normalizeScenarioSets, setMembership, updateSharedLook } from "../../utils/scenarios/scenarioSets";

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

describe("collapsing a set's shared group", () => {
  const sets = [{ id: "park", name: "Park" }, { id: "other", name: "Other" }];

  test("is kept on that set, with where its box was moved", () => {
    const collapsed = updateSharedLook(sets, "park", "outcomes", { collapsed: true });
    expect(collapsed).toEqual([{ id: "park", name: "Park", shared: { outcomes: { collapsed: true } } }, sets[1]]);
    const moved = updateSharedLook(collapsed, "park", "outcomes", { box: { x: 4, y: 5 } });
    expect(moved[0].shared).toEqual({ outcomes: { collapsed: true, box: { x: 4, y: 5 } } });
    // Expanding keeps where the box was, for the next collapse.
    expect(updateSharedLook(moved, "park", "outcomes", { collapsed: false })[0].shared).toEqual({
      outcomes: { box: { x: 4, y: 5 } },
    });
  });

  test("leaves nothing behind once expanded and never moved", () => {
    const collapsed = updateSharedLook(sets, "park", "context", { collapsed: true });
    expect(updateSharedLook(collapsed, "park", "context", { collapsed: false })).toEqual(sets);
  });
});
