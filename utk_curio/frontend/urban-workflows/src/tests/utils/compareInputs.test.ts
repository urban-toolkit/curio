/**
 * The scenarios a node comparing them reads (#662), from the live graph: each
 * input labelled by the scenario its node belongs to (utils/compare/compareInputs).
 */
import { compareInputs, NO_SCENARIO_COLOR } from "../../utils/compare/compareInputs";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

jest.mock("../../utils/palettePackageFactoryDraft", () => ({
  resolveNodeDisplayLabel: (data: any) => data.title ?? data.nodeId,
}));

const COMPARE = "compare";

function node(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "__curioUniversalNode",
    data: { nodeId: id, nodeType: "curio.builtin/computation-analysis@1", code: "return arg", ...extra },
  } as any;
}

function edge(source: string, target: string, targetHandle = "in") {
  return { id: `${source}-${target}-${targetHandle}`, source, target, sourceHandle: "out", targetHandle } as any;
}

const scenario = (id: string, name: string, color: string, nodes: string[]): Scenario => ({ id, name, color, nodes });

const factor = (value: number) => [{ name: "factor", type: "number", default: 1, value }];

/**
 * load -> scale -> chart in Baseline; load -> scale copy -> chart copy in
 * Twice as tall, each copy naming its original. Both charts feed the compare
 * node, on circles 0 and 1.
 */
function twoScenarios() {
  const nodes = [
    node("load", { title: "Loader" }),
    node("scale", { title: "Scale", widgets: factor(1), code: "gdf = arg.copy()\ngdf['h'] = gdf['h'] * [!! factor !!]\nreturn gdf" }),
    node("chart", { title: "Sunlight" }),
    node("scale-2", {
      title: "Scale",
      widgets: factor(2),
      copiedFrom: ["scale"],
      code: "gdf = arg.copy()\ngdf['h'] = gdf['h'] * [!! factor !!]\ngdf = gdf[gdf['h'] > 0]\nreturn gdf",
    }),
    node("chart-2", { title: "Sunlight", copiedFrom: ["chart"] }),
    node(COMPARE, { nodeType: "curio.builtin/vis-vega@1", title: "Compare" }),
  ];
  const edges = [
    edge("load", "scale"),
    edge("scale", "chart"),
    edge("load", "scale-2"),
    edge("scale-2", "chart-2"),
    edge("chart", COMPARE, "in"),
    edge("chart-2", COMPARE, "in_1"),
  ];
  const scenarios = [
    scenario("s-base", "Baseline", "#2a9d8f", ["scale", "chart"]),
    scenario("s-tall", "Twice as tall", "#e76f51", ["scale-2", "chart-2"]),
  ];
  return { nodes, edges, scenarios };
}

describe("compareInputs", () => {
  test("labels each circle by the scenario its node belongs to, in circle order", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    // Listed out of order: the circle decides.
    const inputs = compareInputs(COMPARE, nodes, [...edges].reverse(), scenarios);
    expect(inputs.map((input) => [input.slot, input.source, input.label])).toEqual([
      [0, "chart", { scenario: "s-base", name: "Baseline", color: "#2a9d8f" }],
      [1, "chart-2", { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" }],
    ]);
  });

  test("an input whose node is in no scenario carries the node's name and a neutral color", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const inputs = compareInputs(COMPARE, nodes, [...edges, edge("load", COMPARE, "in_2")], scenarios);
    expect(inputs[2]).toEqual({ slot: 2, source: "load", scenario: null, label: { name: "Loader", color: NO_SCENARIO_COLOR } });
  });

  test("an interaction edge is not an input, and a member deleted since the save labels nothing", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const interaction = { id: "i", source: "chart", target: COMPARE, sourceHandle: "in/out", targetHandle: "in/out" } as any;
    const live = nodes.filter((n) => n.id !== "chart-2");
    const inputs = compareInputs(COMPARE, live, [...edges, interaction], scenarios);
    expect(inputs.map((input) => input.slot)).toEqual([0, 1]);
    expect(inputs[1].scenario).toBeNull();
  });

});
