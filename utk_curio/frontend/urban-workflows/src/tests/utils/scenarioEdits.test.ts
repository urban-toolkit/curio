/**
 * The canvas's edits to a dataflow's scenarios (#662). A node belongs to one
 * scenario, so an edit that would put it in two is refused, naming the
 * scenario that holds it.
 */
import {
  SCENARIO_COLORS,
  addNodesToScenario,
  createScenario,
  deleteScenario,
  nextScenarioColor,
  nextScenarioName,
  removeNodesFromScenarios,
  scenarioHoldingExactly,
  updateScenario,
} from "../../utils/scenarios/scenarioEdits";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import { liveScenarios } from "../../utils/scenarios/scenarioParts";

const baseline: Scenario = { id: "s1", name: "Baseline", color: SCENARIO_COLORS[0], nodes: ["a", "b"] };

describe("createScenario", () => {
  test("holds the nodes, named and colored after the ones there are", () => {
    const edit = createScenario([baseline], ["c", "c", "d"], { id: "s2" });
    expect(edit.error).toBeUndefined();
    expect(edit.scenarios![1]).toEqual({ id: "s2", name: "Scenario 1", color: SCENARIO_COLORS[1], nodes: ["c", "d"] });
  });

  test("is refused for a node another scenario holds, naming that scenario", () => {
    const edit = createScenario([baseline], ["b", "c"], { id: "s2" });
    expect(edit.scenarios).toBeUndefined();
    expect(edit.error).toBe('A node is already in "Baseline". A node belongs to one scenario.');
    expect(createScenario([baseline], ["a", "b"], { id: "s2" }).error).toMatch(/^2 nodes are already in "Baseline"/);
  });

  test("is refused with nothing selected, saying how to select", () => {
    expect(createScenario([], [], { id: "s2" }).error).toMatch(/Shift and drag/);
  });
});

describe("names and colors", () => {
  test("the next name skips the ones taken", () => {
    const named = (name: string): Scenario => ({ ...baseline, name });
    expect(nextScenarioName([named("Scenario 1"), named("Scenario 3")])).toBe("Scenario 2");
    expect(nextScenarioName([named("Scenario 1")], ["Scenario 2"])).toBe("Scenario 3");
  });

  test("the next color is the first unworn, then round again", () => {
    expect(nextScenarioColor([])).toBe(SCENARIO_COLORS[0]);
    const all = SCENARIO_COLORS.map((color, i) => ({ ...baseline, id: `s${i}`, color }));
    expect(nextScenarioColor(all)).toBe(SCENARIO_COLORS[0]);
  });
});

describe("adding and removing nodes", () => {
  const other: Scenario = { id: "s2", name: "Twice as tall", color: SCENARIO_COLORS[1], nodes: ["c"] };

  test("adds nodes once", () => {
    const edit = addNodesToScenario([baseline, other], "s1", ["b", "d"]);
    expect(edit.scenarios![0].nodes).toEqual(["a", "b", "d"]);
  });

  test("refuses a node of another scenario", () => {
    expect(addNodesToScenario([baseline, other], "s1", ["c"]).error).toMatch(/"Twice as tall"/);
  });

  test("takes nodes out of whichever scenario holds them, leaving the others as they are", () => {
    const next = removeNodesFromScenarios([baseline, other], ["b"]);
    expect(next[0].nodes).toEqual(["a"]);
    expect(next[1]).toBe(other);
  });
});

describe("scenarioHoldingExactly", () => {
  // Duplicate as scenario keeps a selection that already is a scenario as it
  // is, and makes only the copy a new one.
  test("finds the scenario a selection is, in any order", () => {
    expect(scenarioHoldingExactly([baseline], ["b", "a"])).toBe(baseline);
    expect(scenarioHoldingExactly([baseline], ["a"])).toBeUndefined();
    expect(scenarioHoldingExactly([baseline], ["a", "b", "c"])).toBeUndefined();
  });

  test("read on the live nodes, a member deleted since the save does not hide it", () => {
    const stale: Scenario = { ...baseline, nodes: ["a", "gone", "b"] };
    const nodes = [{ id: "a" }, { id: "b" }, { id: "c" }];
    // The list as saved still names the deleted node, so it hides the match...
    expect(scenarioHoldingExactly([stale], ["a", "b"])).toBeUndefined();
    // ...which is why the canvas reads it on the live members.
    const live = liveScenarios([stale], nodes);
    expect(scenarioHoldingExactly(live, ["a", "b"])).toEqual({ ...baseline, nodes: ["a", "b"] });
    expect(createScenario(live, ["c"], { id: "s2" }).error).toBeUndefined();
  });
});

describe("updateScenario and deleteScenario", () => {
  test("a blank name and a color that is not #rrggbb are ignored", () => {
    const [next] = updateScenario([baseline], "s1", { name: "  ", color: "green" });
    expect(next.name).toBe("Baseline");
    expect(next.color).toBe(baseline.color);
  });

  test("an empty description is removed rather than saved", () => {
    const [described] = updateScenario([baseline], "s1", { description: "Every building doubled" });
    expect(described.description).toBe("Every building doubled");
    const [cleared] = updateScenario([described], "s1", { description: "" });
    expect("description" in cleared).toBe(false);
  });

  test("collapse state and the box's place are kept", () => {
    const [next] = updateScenario([baseline], "s1", { collapsed: true, box: { x: 10, y: -4 } });
    expect(next.collapsed).toBe(true);
    expect(next.box).toEqual({ x: 10, y: -4 });
  });

  test("deleting a scenario leaves the others", () => {
    expect(deleteScenario([baseline], "s1")).toEqual([]);
  });
});
