/**
 * A scenario's parts by role, read from the live graph (#662), and the outputs
 * the scenarios save.
 *
 * Its own nodes are its Scenario-specific nodes, and its last nodes those of
 * them whose output nothing in it reads, or that something outside it reads;
 * its shared context and shared outcomes are the lists it keeps, or the ones
 * Curio infers when it keeps none; its boundary is what crosses into it, or
 * into one of its shared outcomes from outside every box and every shared
 * outcome. What saves its output because of the scenarios is what stands for
 * each one's boundary, last nodes and shared outcomes, and nothing else.
 */
import { NodeType } from "../../constants";
import {
  liveScenarios,
  savedSourceNodeIds,
  scenarioParts,
  scenarioSourceNodeIds,
} from "../../utils/scenarios/scenarioParts";
import { dashboardSourceNodeIds } from "../../utils/dashboardLayout";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

function node(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "__curioUniversalNode",
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType: NodeType.PYTHON_COMPUTATION, code: "return input_0", ...extra },
  } as any;
}

/** A Python node that returns its widget *name*'s value to the nodes wired after it. */
const valueNode = (id: string, name: string) =>
  node(id, { code: `return [!! ${name} !!]`, widgets: [{ name, type: "number", default: 1 }] });

const chart = (id: string) => node(id, { nodeType: NodeType.VIS_VEGA, code: "{}" });

function edge(source: string, target: string, handles: Record<string, string> = {}) {
  return { id: `${source}-${target}`, source, target, sourceHandle: "out", targetHandle: "in", ...handles } as any;
}

const scenario = (nodes: string[], extra: Partial<Scenario> = {}): Scenario => ({
  id: "s1",
  name: "Twice as tall",
  color: "#e86a3c",
  nodes,
  ...extra,
});

describe("scenarioParts", () => {
  // load -> pool -> a -> b -> chart, and pool -> other: {a, b} is the scenario.
  const nodes = [node("load"), node("pool"), node("a"), node("b"), chart("chart"), node("other")];
  const edges = [
    edge("load", "pool"),
    edge("pool", "a"),
    edge("a", "b"),
    edge("b", "chart"),
    edge("pool", "other"),
  ];

  test("a scenario that keeps no lists has the context and outcomes Curio infers, and the node entering it as its boundary", () => {
    const s = scenario(["a", "b"]);
    expect(scenarioParts(s, nodes, edges, [s])).toEqual({
      nodes: ["a", "b"],
      // b, which the chart reads; a only feeds b.
      last: ["b"],
      context: ["load", "pool"],
      outcomes: ["chart"],
      boundary: ["pool"],
    });
  });

  test("the lists a scenario keeps are its shared context and outcomes, whatever the edges say", () => {
    const s = scenario(["a", "b"], { context: ["pool"], outcomes: [] });
    expect(scenarioParts(s, nodes, edges, [s])).toEqual({
      nodes: ["a", "b"], last: ["b"], context: ["pool"], outcomes: [], boundary: ["pool"],
    });
  });

  test("a value node wired into its node is its boundary, and one wired into nothing is not", () => {
    const withValue = [
      ...nodes.filter((n) => n.id !== "a"),
      node("a", { code: "return input_0 * input_1" }),
      valueNode("season-node", "season"),
      valueNode("unused-node", "height"),
    ];
    const wired = [...edges, edge("season-node", "a", { targetHandle: "in_1" })];
    const s = scenario(["a", "b"]);
    const parts = scenarioParts(s, withValue, wired, [s]);
    expect(parts.boundary).toEqual(["pool", "season-node"]);
    expect(parts.context).toEqual(["load", "pool", "season-node"]);
  });

  test("a value node inside the scenario is its own node, never its context or an outcome", () => {
    const withValue = [...nodes.filter((n) => n.id !== "a"), node("a", { code: "return input_1" }), valueNode("p", "season")];
    const wired = [...edges, edge("p", "a", { targetHandle: "in_1" })];
    const s = scenario(["p", "a", "b"]);
    const parts = scenarioParts(s, withValue, wired, [s]);
    expect(parts.nodes).toEqual(["p", "a", "b"]);
    expect(parts.boundary).toEqual(["pool"]);
    expect(parts.outcomes).toEqual(["chart"]);
  });

  test("another scenario's box stops its context and outcomes", () => {
    const first = scenario(["a"], { id: "s1" });
    const second = scenario(["b"], { id: "s2", name: "Real heights" });
    expect(scenarioParts(first, nodes, edges, [first, second])).toEqual({
      nodes: ["a"], last: ["a"], context: ["load", "pool"], outcomes: [], boundary: ["pool"],
    });
    expect(scenarioParts(second, nodes, edges, [first, second])).toEqual({
      nodes: ["b"], last: ["b"], context: [], outcomes: ["chart"], boundary: ["a"],
    });
  });

  test("an interaction link is not data the scenario reads", () => {
    const linked = [...edges, edge("other", "a", { sourceHandle: "in/out", targetHandle: "in/out" })];
    const s = scenario(["a", "b"]);
    expect(scenarioParts(s, nodes, linked, [s]).boundary).toEqual(["pool"]);
  });

  test("a member deleted since the last save is not read", () => {
    const s = scenario(["a", "gone", "b"], { context: ["gone", "pool"], outcomes: ["gone"] });
    expect(scenarioParts(s, nodes, edges, [s])).toEqual({
      nodes: ["a", "b"], last: ["b"], context: ["pool"], outcomes: [], boundary: ["pool"],
    });
  });
});

describe("liveScenarios", () => {
  const nodes = [node("a"), node("b")];

  test("cuts each member list to the nodes on the canvas", () => {
    expect(liveScenarios([scenario(["a", "gone", "b"])], nodes)[0].nodes).toEqual(["a", "b"]);
  });

  test("keeps a scenario that lost nothing as the same object", () => {
    const kept = scenario(["a", "b"]);
    expect(liveScenarios([kept], nodes)[0]).toBe(kept);
  });

  test("keeps a scenario whose nodes were all deleted, with none", () => {
    expect(liveScenarios([scenario(["gone"])], nodes)[0].nodes).toEqual([]);
  });
});

describe("the outputs the scenarios save", () => {
  test("what crosses into it, its last node and its shared outcomes, each where it is made; a node deeper upstream saves nothing", () => {
    const nodes = [node("raw"), node("load"), node("a"), node("b")];
    const edges = [edge("raw", "load"), edge("load", "a"), edge("a", "b")];
    expect([...scenarioSourceNodeIds(nodes, edges, [scenario(["a"])])].sort()).toEqual(["a", "b", "load"]);
  });

  test("of its own nodes, the last saves and the one before it saves nothing because of it", () => {
    const nodes = [node("load"), node("a"), node("b")];
    const edges = [edge("load", "a"), edge("a", "b")];
    expect([...scenarioSourceNodeIds(nodes, edges, [scenario(["a", "b"])])].sort()).toEqual(["b", "load"]);
  });

  test("a chart outcome saves nothing itself: the node feeding it does", () => {
    const nodes = [node("load"), node("a"), chart("chart")];
    const edges = [edge("load", "a"), edge("a", "chart")];
    expect([...scenarioSourceNodeIds(nodes, edges, [scenario(["a"])])].sort()).toEqual(["a", "load"]);
  });

  test("a value node in the boundary saves its output, which a drop brings as data", () => {
    const nodes = [node("a"), valueNode("p", "season")];
    expect([...scenarioSourceNodeIds(nodes, [edge("p", "a")], [scenario(["a"])])].sort()).toEqual(["a", "p"]);
  });

  test("the save rule adds the scenarios' to a pinned tile's, and without scenarios is the tile's alone", () => {
    const nodes = [node("load"), node("a"), chart("pinned"), node("x"), node("y"), node("z")];
    nodes[2].data.dashboardPinned = true;
    const edges = [edge("load", "a"), edge("a", "pinned"), edge("x", "y"), edge("y", "z")];
    expect([...savedSourceNodeIds(nodes, edges, [])]).toEqual([...dashboardSourceNodeIds(nodes, edges)]);
    expect([...savedSourceNodeIds(nodes, edges, [scenario(["y"])])].sort()).toEqual(["a", "x", "y", "z"]);
  });
});
