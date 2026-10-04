/**
 * A scenario's fixed context, levers and outcomes, read from the live graph
 * (#662), and the outputs a scenario has saved.
 *
 * The context is what enters the selection: an edge from outside, or a shared
 * tag (`[!! @name !!]`) its code names, which has no edge. The outcomes are the
 * levers whose output nothing inside reads, or that something outside reads.
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
    data: { nodeId: id, nodeType: NodeType.COMPUTATION_ANALYSIS, code: "return arg", ...extra },
  } as any;
}

const parameter = (id: string, name: string) =>
  node(id, { nodeType: "curio.builtin/parameter", code: undefined, widgets: [{ name, type: "number", default: 1 }] });

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
  // load -> pool -> a -> b -> chart, and pool -> other: {a, b} is the branch.
  const nodes = [node("load"), node("pool"), node("a"), node("b"), chart("chart"), node("other")];
  const edges = [
    edge("load", "pool"),
    edge("pool", "a"),
    edge("a", "b"),
    edge("b", "chart"),
    edge("pool", "other"),
  ];

  test("a branch reads its context through the edge entering it, and its last node is the outcome", () => {
    expect(scenarioParts(scenario(["a", "b"]), nodes, edges)).toEqual({
      levers: ["a", "b"],
      context: ["pool"],
      outcomes: ["b"],
    });
  });

  test("a node read inside and outside the selection is an outcome too", () => {
    const parts = scenarioParts(scenario(["pool", "a"]), nodes, edges);
    expect(parts.context).toEqual(["load"]);
    // pool feeds a (inside) and other (outside); a feeds b (outside).
    expect(parts.outcomes).toEqual(["pool", "a"]);
  });

  test("a context reached only through a shared tag is found, though no edge leads from it", () => {
    const withTag = [
      ...nodes.filter((n) => n.id !== "a"),
      node("a", { code: "return arg * [!! @season !!]" }),
      parameter("season-node", "season"),
      parameter("unused-node", "height"),
    ];
    const parts = scenarioParts(scenario(["a", "b"]), withTag, edges);
    expect(parts.context).toEqual(["pool", "season-node"]);
  });

  test("a Parameter node inside the scenario is a lever, never its context or an outcome", () => {
    const withTag = [...nodes.filter((n) => n.id !== "a"), node("a", { code: "[!! @season !!]" }), parameter("p", "season")];
    const parts = scenarioParts(scenario(["p", "a", "b"]), withTag, edges);
    expect(parts.levers).toEqual(["p", "a", "b"]);
    expect(parts.context).toEqual(["pool"]);
    expect(parts.outcomes).toEqual(["b"]);
  });

  test("a whole-dataflow scenario has no context", () => {
    const parts = scenarioParts(scenario(nodes.map((n) => n.id)), nodes, edges);
    expect(parts.context).toEqual([]);
    expect(parts.outcomes).toEqual(["chart", "other"]);
  });

  test("an interaction link is not data the scenario reads", () => {
    const linked = [...edges, edge("other", "a", { sourceHandle: "in/out", targetHandle: "in/out" })];
    expect(scenarioParts(scenario(["a", "b"]), nodes, linked).context).toEqual(["pool"]);
  });

  test("a member deleted since the last save is not read", () => {
    const parts = scenarioParts(scenario(["a", "gone", "b"]), nodes, edges);
    expect(parts.levers).toEqual(["a", "b"]);
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

describe("the outputs a scenario saves", () => {
  test("its context and its outcomes, each where it is made", () => {
    const nodes = [node("load"), node("a"), node("b")];
    const edges = [edge("load", "a"), edge("a", "b")];
    expect([...scenarioSourceNodeIds(nodes, edges, [scenario(["a", "b"])])].sort()).toEqual(["b", "load"]);
  });

  test("a chart outcome saves nothing itself: the node feeding it does", () => {
    const nodes = [node("load"), node("a"), chart("chart")];
    const edges = [edge("load", "a"), edge("a", "chart")];
    expect([...scenarioSourceNodeIds(nodes, edges, [scenario(["a", "chart"])])].sort()).toEqual(["a", "load"]);
  });

  test("a Parameter node in the context saves nothing: its value is in the spec", () => {
    const nodes = [node("a", { code: "[!! @season !!]" }), parameter("p", "season")];
    expect([...scenarioSourceNodeIds(nodes, [], [scenario(["a"])])]).toEqual(["a"]);
  });

  test("the save rule adds a scenario's to a pinned tile's, and without scenarios is the tile's alone", () => {
    const nodes = [node("load"), node("a"), chart("pinned"), node("x"), node("y")];
    nodes[2].data.dashboardPinned = true;
    const edges = [edge("load", "a"), edge("a", "pinned"), edge("x", "y")];
    expect([...savedSourceNodeIds(nodes, edges, [])]).toEqual([...dashboardSourceNodeIds(nodes, edges)]);
    expect([...savedSourceNodeIds(nodes, edges, [scenario(["y"])])].sort()).toEqual(["a", "x", "y"]);
  });
});
