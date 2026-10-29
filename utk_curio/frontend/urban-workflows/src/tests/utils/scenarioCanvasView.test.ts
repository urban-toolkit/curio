/**
 * How the canvas draws scenarios (#662): `scenarioCanvasView`, called where
 * MainCanvas hands nodes and edges to React Flow.
 *
 * A collapsed scenario's members stay mounted, hidden the way the dashboard
 * hides an unpinned node (`hideNode`); the edges they touch are hidden, and an
 * edge crossing the scenario's edge is drawn to or from its box. None of it is
 * dataflow state: the last block checks that the save, Run All's levels and
 * an agent's view read the same graph collapsed, expanded or with no scenario.
 */
jest.mock("../../registry/nodeRegistry", () => ({ getPaletteNodeTypes: () => [], tryGetNodeDescriptor: () => undefined }));

import { NodeType } from "../../constants";
import { TrillGenerator } from "../../TrillGenerator";
import { computeTopologicalLevels } from "../../providers/flow/runLevels";
import { composeAgentRunContext, type AgentAttachment } from "../../services/agents";
import { prepareDashboardNodes } from "../../utils/dashboardLayout";
import { hideNode } from "../../utils/hiddenNodes";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import {
  SCENARIO_FIXED_CLASS,
  SCENARIO_MEMBER_CLASS,
  SCENARIO_OUTCOME_CLASS,
  scenarioCanvasView,
} from "../../utils/scenarios/scenarioCanvasView";

function node(id: string, x: number, y: number, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "__curioUniversalNode",
    position: { x, y },
    width: 300,
    height: 200,
    data: { nodeId: id, nodeType: NodeType.COMPUTATION_ANALYSIS, code: `return '${id}'`, ...extra },
  } as any;
}

function edge(source: string, target: string, targetHandle = "in") {
  return { id: `${source}-${target}`, source, target, sourceHandle: "out", targetHandle, type: "UNIDIRECTIONAL_EDGE" } as any;
}

// load -> pool -> a -> map -> chart, and pool -> b: {a, map} is a branch.
const NODES = [
  node("load", 0, 0),
  node("pool", 400, 0),
  node("a", 800, 100),
  node("map", 1200, 80, { nodeType: NodeType.AUTK_GRAMMAR, code: "{}" }),
  node("chart", 1600, 0, { nodeType: NodeType.VIS_VEGA, code: "{}" }),
  node("b", 800, 500),
];
const EDGES = [edge("load", "pool"), edge("pool", "a"), edge("a", "map"), edge("map", "chart"), edge("pool", "b")];

const branch = (extra: Partial<Scenario> = {}): Scenario => ({
  id: "tall",
  name: "Twice as tall",
  color: "#e86a3c",
  nodes: ["a", "map"],
  ...extra,
});

describe("scenarioCanvasView", () => {
  test("with no scenario it hands back the very same arrays", () => {
    const view = scenarioCanvasView(NODES, EDGES, []);
    expect(view.nodes).toBe(NODES);
    expect(view.edges).toBe(EDGES);
    expect([view.boxes, view.frames, view.standIns]).toEqual([[], [], []]);
  });

  test("a scenario whose nodes were all deleted draws nothing", () => {
    const view = scenarioCanvasView(NODES, EDGES, [branch({ nodes: ["gone"], collapsed: true })]);
    expect(view.nodes).toBe(NODES);
    expect(view.boxes).toEqual([]);
  });

  test("a collapsed scenario's members stay mounted, hidden as the dashboard hides a node", () => {
    const selected = NODES.map((n) => (n.id === "a" ? { ...n, selected: true } : n));
    const view = scenarioCanvasView(selected, EDGES, [branch({ collapsed: true })]);
    const a = view.nodes.find((n) => n.id === "a")!;
    expect(a).toEqual({ ...hideNode(selected[2]), selected: false });
    expect(a.style).toEqual({ display: "none" });
    expect([a.draggable, a.selectable, a.hidden]).toEqual([false, false, undefined]);
    // The dashboard hides an unpinned node with the same helper.
    const dashboard = prepareDashboardNodes([NODES[2]], [], {}).nodes[0];
    expect(dashboard.style).toEqual(a.style);
    expect([dashboard.draggable, dashboard.selectable]).toEqual([false, false]);
  });

  test("nodes outside every scenario keep their identity", () => {
    const view = scenarioCanvasView(NODES, EDGES, [branch({ collapsed: true })]);
    for (const id of ["load", "pool", "chart", "b"]) {
      expect(view.nodes.find((n) => n.id === id)).toBe(NODES.find((n) => n.id === id));
    }
    expect(view.edges.find((e) => e.id === "pool-b")).toBe(EDGES[4]);
  });

  test("the edges a collapsed scenario's members touch are hidden, and the crossing ones drawn to its box", () => {
    const view = scenarioCanvasView(NODES, EDGES, [branch({ collapsed: true })]);
    expect(view.edges.filter((e) => e.hidden).map((e) => e.id)).toEqual(["pool-a", "a-map", "map-chart"]);
    expect(view.standIns.map((s) => [s.source, s.target])).toEqual([
      [{ node: "pool", handle: "out" }, { box: "tall", port: "in", of: "a" }],
      [{ box: "tall", port: "out", of: "map" }, { node: "chart", handle: "in" }],
    ]);
  });

  test("an edge enters a box at the card of the node it enters", () => {
    const twice = [...EDGES, edge("pool", "map", "in_1")];
    const view = scenarioCanvasView(NODES, twice, [branch({ collapsed: true })]);
    expect(view.standIns.filter((s) => "box" in s.target).map((s) => s.target)).toEqual([
      { box: "tall", port: "in", of: "a" },
      { box: "tall", port: "in", of: "map" },
    ]);
  });

  test("between two collapsed scenarios a stand-in runs box to box", () => {
    const view = scenarioCanvasView(NODES, EDGES, [
      { id: "base", name: "Baseline", color: "#3567c7", nodes: ["load", "pool"], collapsed: true },
      branch({ collapsed: true }),
    ]);
    expect(view.standIns.find((s) => "box" in s.source && "box" in s.target)).toEqual({
      id: expect.any(String),
      source: { box: "base", port: "out", of: "pool" },
      target: { box: "tall", port: "in", of: "a" },
    });
  });

  test("a box sits at its members' top left, or where it was moved", () => {
    expect(scenarioCanvasView(NODES, EDGES, [branch({ collapsed: true })]).boxes[0]).toMatchObject({
      x: 800,
      y: 80,
      parts: { levers: ["a", "map"], context: ["pool"], outcomes: ["map"] },
      rows: ["a", "map"],
    });
    const moved = scenarioCanvasView(NODES, EDGES, [branch({ collapsed: true, box: { x: -5, y: 7 } })]).boxes[0];
    expect([moved.x, moved.y]).toEqual([-5, 7]);
  });

  test("an expanded scenario's members wear its color, inside a frame", () => {
    const view = scenarioCanvasView(NODES, EDGES, [branch()]);
    const a = view.nodes.find((n) => n.id === "a")!;
    expect(a.className).toBe(SCENARIO_MEMBER_CLASS);
    expect((a.style as Record<string, unknown>)["--scenario-color"]).toBe("#e86a3c");
    expect(view.frames).toEqual([{ scenario: branch(), members: ["a", "map"] }]);
    expect(view.boxes).toEqual([]);
    expect(view.edges).toEqual(EDGES);
  });

  test("the scenario the panel highlights has its fixed context marked", () => {
    const view = scenarioCanvasView(NODES, EDGES, [branch()], { fixedFor: "tall" });
    expect(view.nodes.filter((n) => n.className?.includes(SCENARIO_FIXED_CLASS)).map((n) => n.id)).toEqual(["pool"]);
  });

  test("with none highlighted or being defined, nothing is marked", () => {
    const view = scenarioCanvasView(NODES, EDGES, [branch({ context: ["pool"], outcomes: ["chart"] })]);
    const marked = (cls: string) => view.nodes.filter((n) => n.className?.includes(cls)).map((n) => n.id);
    expect(marked(SCENARIO_FIXED_CLASS)).toEqual([]);
    expect(marked(SCENARIO_OUTCOME_CLASS)).toEqual([]);
  });
});

describe("a set's shared context and shared outcomes", () => {
  // Two scenarios of one set: {a, map} and {b}, both fed by load and pool.
  const tall = branch({ set: "park", context: ["load", "pool"], outcomes: ["chart"] });
  const other: Scenario = { id: "other", name: "Other", color: "#3567c7", nodes: ["b"], set: "park", context: ["pool"] };
  const sets = (shared = {}) => [{ id: "park", name: "Park", shared }];

  test("are a group each, in the dataflow's order, at their nodes' top left", () => {
    const view = scenarioCanvasView(NODES, EDGES, [tall, other], { sets: sets() });
    expect(view.groups).toEqual([
      { key: "group:park:context", set: "park", kind: "context", nodes: ["load", "pool"], collapsed: false, x: 0, y: 0 },
      { key: "group:park:outcomes", set: "park", kind: "outcomes", nodes: ["chart"], collapsed: false, x: 1600, y: 0 },
    ]);
    expect(view.sets).toEqual([{ set: "park", frames: ["tall", "other"], boxes: [], groups: view.groups!.map((g) => g.key) }]);
  });

  test("collapsed, a group's nodes are hidden, and the edges crossing it drawn from its box's cards", () => {
    const view = scenarioCanvasView(NODES, EDGES, [tall, other], {
      sets: sets({ context: { collapsed: true, box: { x: -50, y: 9 } } }),
    });
    const context = view.groups!.find((g) => g.kind === "context")!;
    expect([context.collapsed, context.x, context.y]).toEqual([true, -50, 9]);
    expect(view.nodes.find((n) => n.id === "load")).toEqual({ ...hideNode(NODES[0]), selected: false });
    expect(view.edges.filter((e) => e.hidden).map((e) => e.id)).toEqual(["load-pool", "pool-a", "pool-b"]);
    // load -> pool stays inside the box; pool leaves it twice.
    expect(view.standIns.map((s) => [s.source, s.target])).toEqual([
      [{ box: "group:park:context", port: "out", of: "pool" }, { node: "a", handle: "in" }],
      [{ box: "group:park:context", port: "out", of: "pool" }, { node: "b", handle: "in" }],
    ]);
  });

  test("a collapsed group and a collapsed scenario are joined box to box", () => {
    const view = scenarioCanvasView(NODES, EDGES, [{ ...tall, collapsed: true }, other], {
      sets: sets({ outcomes: { collapsed: true } }),
    });
    expect(view.standIns.find((s) => s.target && "box" in s.target && s.target.box === "group:park:outcomes")).toEqual(
      {
        id: expect.any(String),
        source: { box: "tall", port: "out", of: "map" },
        target: { box: "group:park:outcomes", port: "in", of: "chart" },
      },
    );
  });
});

describe("collapsing changes nothing but the drawing", () => {
  const reader: AgentAttachment = {
    attachmentId: "a1",
    coord: "agent.curio.dataflow-reader@1",
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

  beforeEach(() => {
    TrillGenerator.reset();
    jest.spyOn(Date, "now").mockReturnValue(1748990000000);
  });
  afterEach(() => jest.restoreAllMocks());

  /** What a save writes, without the one key a collapse changes. */
  function saved(nodes: any[], edges: any[], scenarios: Scenario[]) {
    const spec = TrillGenerator.generateTrill(nodes, edges, "06", "", [], "", [], {}, scenarios);
    const rest = { ...spec.dataflow };
    delete rest.scenarios;
    delete rest.scenarioSets;
    return rest;
  }

  function agentView(nodes: any[], edges: any[], scenarios: Scenario[]) {
    const context = composeAgentRunContext(reader, { nodes, edges, workflowName: "06", workflowGoal: "", scenarios });
    const trill = JSON.parse(String(context).replace(/^Current Trill: /, ""));
    delete trill.dataflow.scenarios;
    delete trill.dataflow.scenarioSets;
    return trill;
  }

  const collapsed = [branch({ collapsed: true })];
  const expanded = [branch({ collapsed: false })];

  // React Flow's store holds what the view hands it: that is what a save,
  // Run All and an agent read through `reactFlow.getNodes()`.
  test.each([
    ["collapsed", collapsed],
    ["expanded again", expanded],
  ])("%s, the save, the run levels and an agent's view are what they are with no scenario", (_label, scenarios) => {
    const view = scenarioCanvasView(NODES, EDGES, scenarios);
    expect(saved(view.nodes, view.edges, scenarios)).toEqual(saved(NODES, EDGES, []));
    expect(computeTopologicalLevels(view.nodes, view.edges)).toEqual(computeTopologicalLevels(NODES, EDGES));
    expect(agentView(view.nodes, view.edges, scenarios)).toEqual(agentView(NODES, EDGES, []));
  });

  test("the saved scenario says whether it is collapsed, and that is all that differs", () => {
    const view = scenarioCanvasView(NODES, EDGES, collapsed);
    const spec = TrillGenerator.generateTrill(view.nodes, view.edges, "06", "", [], "", [], {}, collapsed);
    expect(spec.dataflow.scenarios).toEqual(collapsed.map((s) => expect.objectContaining(s)));
    expect(spec.dataflow.scenarios[0].collapsed).toBe(true);
  });
});
