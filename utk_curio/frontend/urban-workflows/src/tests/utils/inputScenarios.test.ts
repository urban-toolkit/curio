/**
 * The scenario box each of a node's inputs comes from (#662): the node feeding
 * each circle, the box it is in, and the label the input's rows are named and
 * drawn by. A chart reading `inputs`, an Autark map and a Compare Scenarios
 * node all find an input's box this way.
 */
import { inputLabelOf, inputScenarios, scaleLabelsOf, scenarioOfNode } from "../../utils/scenarios/inputScenarios";
import { NO_SCENARIO_COLOR } from "../../utils/scenarios/scenarioColors";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

jest.mock("../../utils/palettePackageFactoryDraft", () => ({
  resolveNodeDisplayLabel: (data: any) => data.nodeType,
}));

const CHART = "chart";

function node(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "__curioUniversalNode",
    data: { nodeId: id, nodeType: "curio.builtin/computation-analysis@1", ...extra },
  } as any;
}

function edge(source: string, target: string, targetHandle = "in") {
  return { id: `${source}-${target}-${targetHandle}`, source, target, sourceHandle: "out", targetHandle } as any;
}

const box = (id: string, name: string, color: string, nodes: string[]): Scenario => ({ id, name, color, nodes });

/** load feeds base (in Baseline) and tall (in Twice as tall); both feed the chart, on circles 0 and 1. */
function twoBoxes() {
  const nodes = [
    node("load", { title: "Loader" }),
    node("base", { title: "Shade" }),
    node("tall", { title: "Shade" }),
    node(CHART, { nodeType: "curio.builtin/vis-vega@1" }),
  ];
  const edges = [edge("load", "base"), edge("load", "tall"), edge("base", CHART, "in"), edge("tall", CHART, "in_1")];
  const scenarios = [box("s-base", "Baseline", "#2a9d8f", ["base"]), box("s-tall", "Twice as tall", "#e76f51", ["tall"])];
  return { nodes, edges, scenarios };
}

describe("inputScenarios", () => {
  test("labels each circle by the box its node is in, in circle order", () => {
    const { nodes, edges, scenarios } = twoBoxes();
    // Listed out of order: the circle decides.
    const inputs = inputScenarios(CHART, nodes, [...edges].reverse(), scenarios);
    expect(inputs.map((input) => [input.slot, input.source, input.scenario?.id, input.label])).toEqual([
      [0, "base", "s-base", { scenario: "s-base", name: "Baseline", color: "#2a9d8f" }],
      [1, "tall", "s-tall", { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" }],
    ]);
  });

  test("each input is labelled in circle order, whatever order the dataflow lists the boxes in", () => {
    const { nodes, edges, scenarios } = twoBoxes();
    const inputs = inputScenarios(CHART, nodes, edges, [...scenarios].reverse());
    expect(inputs.map((input) => input.label.name)).toEqual(["Baseline", "Twice as tall"]);
  });

  test("an input whose node is in no box carries the node's name and a neutral color", () => {
    const { nodes, edges, scenarios } = twoBoxes();
    const inputs = inputScenarios(CHART, nodes, [...edges, edge("load", CHART, "in_2")], scenarios);
    expect(inputs[2]).toEqual({ slot: 2, source: "load", scenario: null, label: { name: "Loader", color: NO_SCENARIO_COLOR } });
  });

  test("a node with no title is named by its header's label", () => {
    const { nodes, edges, scenarios } = twoBoxes();
    const plain = node("plain");
    const inputs = inputScenarios(CHART, [...nodes, plain], [...edges, edge("plain", CHART, "in_2")], scenarios);
    expect(inputs[2].label).toEqual({ name: "curio.builtin/computation-analysis@1", color: NO_SCENARIO_COLOR });
  });

  test("an interaction edge is not an input, and a member deleted since the save labels nothing", () => {
    const { nodes, edges, scenarios } = twoBoxes();
    const interaction = { id: "i", source: "base", target: CHART, sourceHandle: "in/out", targetHandle: "in/out" } as any;
    const live = nodes.filter((n) => n.id !== "tall");
    const inputs = inputScenarios(CHART, live, [...edges, interaction], scenarios);
    expect(inputs.map((input) => input.slot)).toEqual([0, 1]);
    expect(inputs[1].scenario).toBeNull();
  });

  test("a node two boxes name is in the first", () => {
    const { nodes, edges, scenarios } = twoBoxes();
    const both = [...scenarios, box("s-again", "Again", "#000000", ["base"])];
    expect(inputScenarios(CHART, nodes, edges, both)[0].label.scenario).toBe("s-base");
  });

  test("no edge into the node, no input", () => {
    const { nodes, edges, scenarios } = twoBoxes();
    expect(inputScenarios("load", nodes, edges, scenarios)).toEqual([]);
  });
});

describe("scaleLabelsOf: the order a chart's scales draw its inputs' boxes in", () => {
  test("the order the dataflow lists its boxes in, not the circles'", () => {
    const { nodes, edges, scenarios } = twoBoxes();
    const listed = [...scenarios].reverse();
    const labels = scaleLabelsOf(inputScenarios(CHART, nodes, edges, listed), listed);
    expect(labels.map((label) => label.name)).toEqual(["Twice as tall", "Baseline"]);
  });

  test("each box once, then each input from no box in circle order, in a neutral color", () => {
    const { nodes, edges, scenarios } = twoBoxes();
    const more = [
      ...edges,
      edge("load", CHART, "in_2"),
      edge("base", CHART, "in_3"),
      edge("plain", CHART, "in_4"),
    ];
    const labels = scaleLabelsOf(inputScenarios(CHART, [...nodes, node("plain", { title: "Plain" })], more, scenarios), scenarios);
    expect(labels).toEqual([
      { scenario: "s-base", name: "Baseline", color: "#2a9d8f" },
      { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" },
      { name: "Loader", color: NO_SCENARIO_COLOR },
      { name: "Plain", color: NO_SCENARIO_COLOR },
    ]);
  });
});

describe("scenarioOfNode and inputLabelOf", () => {
  test("the box a node sits in, or none", () => {
    const { nodes, scenarios } = twoBoxes();
    expect(scenarioOfNode("tall", nodes, scenarios)?.id).toBe("s-tall");
    expect(scenarioOfNode(CHART, nodes, scenarios)).toBeNull();
    // A box's member that left the canvas is not in it.
    expect(scenarioOfNode("tall", nodes.filter((n) => n.id !== "tall"), scenarios)).toBeNull();
  });

  test("a box names an input by its id, name and color; no box, by the node", () => {
    const [baseline] = twoBoxes().scenarios;
    expect(inputLabelOf(baseline, node("base"), "base")).toEqual({ scenario: "s-base", name: "Baseline", color: "#2a9d8f" });
    expect(inputLabelOf(null, node("load", { title: "Loader" }), "load")).toEqual({ name: "Loader", color: NO_SCENARIO_COLOR });
  });
});
