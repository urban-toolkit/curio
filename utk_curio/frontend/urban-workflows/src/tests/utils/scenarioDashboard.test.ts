/**
 * The dashboard by scenario (#662): the tiles the scenarios share come first,
 * then one column per scenario, then the tiles that read their outcomes. A
 * shared Parameter node has no edge, so it is found as the scenarios' context
 * through its tag. With no pinned tile in a scenario, the dashboard keeps the
 * layout it has always had.
 */
import { NodeType } from "../../constants";
import {
  DASHBOARD_TILE_DEFAULT_HEIGHT,
  DASHBOARD_TILE_DEFAULT_WIDTH,
  arrangedTilePositions,
  prepareDashboardNodes,
} from "../../utils/dashboardLayout";
import { scenarioDashboard } from "../../utils/scenarios/scenarioDashboard";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

function node(id: string, at: { x: number; y: number }, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "__curioUniversalNode",
    position: at,
    data: { nodeId: id, nodeType: NodeType.COMPUTATION_ANALYSIS, code: "return arg", ...extra },
  } as any;
}

const parameter = (id: string, name: string, at: { x: number; y: number }) =>
  node(id, at, { nodeType: "curio.builtin/parameter", code: undefined, widgets: [{ name, type: "number", default: 1 }] });

function edge(source: string, target: string, targetHandle = "in") {
  return { id: `${source}-${target}`, source, target, sourceHandle: "out", targetHandle } as any;
}

const BASE: Scenario = { id: "base", name: "Baseline", color: "#2a9d8f", nodes: [] };
const TALL: Scenario = { id: "tall", name: "Twice as tall", color: "#e86a3c", nodes: [] };

/**
 * A loader feeding two scenarios of two nodes each, and a comparison reading
 * both outcomes. The canvas puts each chain's second node above its first, so
 * an order by canvas position alone would put them the wrong way round.
 */
function shadows() {
  const nodes = [
    node("load", { x: 0, y: 300 }),
    node("a1", { x: 600, y: 200 }),
    node("a2", { x: 1200, y: 0 }),
    node("b1", { x: 600, y: 900 }),
    node("b2", { x: 1200, y: 700 }),
    node("compare", { x: 1800, y: 400 }),
  ];
  const edges = [
    edge("load", "a1"),
    edge("a1", "a2"),
    edge("load", "b1"),
    edge("b1", "b2"),
    edge("a2", "compare"),
    edge("b2", "compare", "in_1"),
  ];
  const scenarios = [
    { ...BASE, nodes: ["a1", "a2"] },
    { ...TALL, nodes: ["b1", "b2"] },
  ];
  const pins = Object.fromEntries(nodes.map((n) => [n.id, true]));
  return { nodes, edges, scenarios, pins };
}

function laidOut(
  nodes: any[],
  edges: any[],
  pins: Record<string, boolean>,
  scenarios: Scenario[],
) {
  const columns = scenarioDashboard(nodes, edges, pins, scenarios)?.columns;
  const prepared = prepareDashboardNodes(nodes, edges, pins, columns);
  return new Map(prepared.nodes.map((n) => [n.id, n.position]));
}

describe("the columns", () => {
  test("the shared context comes first, then one column per scenario, then what reads their outcomes", () => {
    const { nodes, edges, scenarios, pins } = shadows();
    expect(scenarioDashboard(nodes, edges, pins, scenarios)?.columns).toEqual([
      ["load"],
      ["a1", "a2"],
      ["b1", "b2"],
      ["compare"],
    ]);
  });

  test("on the page each column has its own x, left to right, and stacks its tiles upstream first", () => {
    const { nodes, edges, scenarios, pins } = shadows();
    const at = laidOut(nodes, edges, pins, scenarios);
    const x = (id: string) => at.get(id)!.x;
    const y = (id: string) => at.get(id)!.y;

    expect(x("load")).toBeLessThan(x("a1"));
    expect([x("a1"), x("b1")]).toEqual([x("a2"), x("b2")]);
    expect(x("a1")).toBeLessThan(x("b1"));
    expect(x("b1")).toBeLessThan(x("compare"));
    expect(y("a2") - y("a1")).toBeGreaterThanOrEqual(DASHBOARD_TILE_DEFAULT_HEIGHT);
    expect(y("b2") - y("b1")).toBeGreaterThanOrEqual(DASHBOARD_TILE_DEFAULT_HEIGHT);
  });

  test("the scenarios' columns follow the order of the dataflow's scenarios", () => {
    const { nodes, edges, scenarios, pins } = shadows();
    const columns = scenarioDashboard(nodes, edges, pins, [...scenarios].reverse())?.columns;
    expect(columns).toEqual([["load"], ["b1", "b2"], ["a1", "a2"], ["compare"]]);
  });

  test("a shared Parameter node, read only through its tag, sits with the context", () => {
    const nodes = [
      parameter("season", "season", { x: 0, y: 900 }),
      node("load", { x: 0, y: 0 }),
      node("a", { x: 600, y: 0 }, { code: "return arg * [!! @season !!]" }),
      node("b", { x: 600, y: 600 }, { code: "return arg * [!! @season !!] * 2" }),
    ];
    const edges = [edge("load", "a"), edge("load", "b")];
    const scenarios = [
      { ...BASE, nodes: ["a"] },
      { ...TALL, nodes: ["b"] },
    ];
    const pins = { season: true, load: true, a: true, b: true };

    // An edgeless node comes first in Run All's levels, so it heads the column.
    expect(scenarioDashboard(nodes, edges, pins, scenarios)?.columns).toEqual([
      ["season", "load"],
      ["a"],
      ["b"],
    ]);
    const at = laidOut(nodes, edges, pins, scenarios);
    expect(at.get("season")!.x).toBe(at.get("load")!.x);
    expect(at.get("season")!.x).toBeLessThan(at.get("a")!.x);
  });

  test("a Parameter node inside a scenario is its lever, and stays in its column", () => {
    const nodes = [
      node("load", { x: 0, y: 0 }),
      parameter("height", "height", { x: 600, y: 600 }),
      node("a", { x: 600, y: 0 }, { code: "return arg * [!! @height !!]" }),
      node("b", { x: 600, y: 1200 }),
    ];
    const edges = [edge("load", "a"), edge("load", "b")];
    const scenarios = [
      { ...BASE, nodes: ["height", "a"] },
      { ...TALL, nodes: ["b"] },
    ];
    const pins = { load: true, height: true, a: true, b: true };

    expect(scenarioDashboard(nodes, edges, pins, scenarios)?.columns).toEqual([
      ["load"],
      ["height", "a"],
      ["b"],
    ]);
  });

  test("only pinned tiles are placed, and a scenario with none pinned has no column", () => {
    const { nodes, edges, scenarios } = shadows();
    const pins = { load: true, a2: true, compare: true };
    const result = scenarioDashboard(nodes, edges, pins, scenarios)!;

    expect(result.columns).toEqual([["load"], ["a2"], ["compare"]]);
    expect(result.frames.map((f) => [f.scenario.id, f.members])).toEqual([["base", ["a2"]]]);
  });

  test("each scenario's frame holds its pinned tiles, in its color", () => {
    const { nodes, edges, scenarios, pins } = shadows();
    const { frames } = scenarioDashboard(nodes, edges, pins, scenarios)!;

    expect(frames.map((f) => [f.scenario.name, f.scenario.color, f.members])).toEqual([
      ["Baseline", "#2a9d8f", ["a1", "a2"]],
      ["Twice as tall", "#e86a3c", ["b1", "b2"]],
    ]);
  });

  test("a member deleted since the last save is not a tile", () => {
    const { nodes, edges, pins } = shadows();
    const scenarios = [{ ...BASE, nodes: ["a1", "a2", "gone"] }];
    const { columns } = scenarioDashboard(nodes, edges, pins, scenarios)!;
    expect(columns.flat()).not.toContain("gone");
  });
});

describe("without a pinned tile in a scenario", () => {
  test("no scenarios gives the layout the dashboard has always had: a column per distance from the first tile", () => {
    const { nodes, edges, pins } = shadows();

    expect(scenarioDashboard(nodes, edges, pins, [])).toBeNull();
    const at = laidOut(nodes, edges, pins, []);
    const column = DASHBOARD_TILE_DEFAULT_WIDTH + 40;
    const row = DASHBOARD_TILE_DEFAULT_HEIGHT + 20;
    expect(Object.fromEntries(at)).toEqual({
      load: { x: 0, y: 50 },
      a1: { x: column, y: 50 },
      b1: { x: column, y: 50 + row },
      a2: { x: 2 * column, y: 50 },
      b2: { x: 2 * column, y: 50 + row },
      compare: { x: 3 * column, y: 50 },
    });
  });

  test("scenarios whose nodes are not pinned give it too", () => {
    const { nodes, edges, scenarios } = shadows();
    const pins = { load: true, compare: true };

    expect(scenarioDashboard(nodes, edges, pins, scenarios)).toBeNull();
    expect(laidOut(nodes, edges, pins, scenarios)).toEqual(
      new Map(prepareDashboardNodes(nodes, edges, pins).nodes.map((n) => [n.id, n.position])),
    );
  });
});

describe("saved slots", () => {
  test("a saved slot still wins when the page opens", () => {
    const { nodes, edges, scenarios, pins } = shadows();
    const moved = nodes.map((n) => (n.id === "a1" ? { ...n, data: { ...n.data, dashboardX: 5, dashboardY: 7 } } : n));

    expect(laidOut(moved, edges, pins, scenarios).get("a1")).toEqual({ x: 5, y: 7 });
  });

  test("Arrange by scenario puts every tile in its column, whatever slot it was saved in", () => {
    const { nodes, edges, scenarios, pins } = shadows();
    const columns = scenarioDashboard(nodes, edges, pins, scenarios)!.columns;
    const fresh = prepareDashboardNodes(nodes, edges, pins, columns).nodes;
    // Opened, then a tile dragged away and its slot saved.
    const dragged = fresh.map((n) =>
      n.id === "a1"
        ? { ...n, position: { x: 9000, y: 9000 }, data: { ...n.data, dashboardX: 9000, dashboardY: 9000 } }
        : n,
    );

    const arranged = arrangedTilePositions(dragged, pins, columns);

    expect([...arranged.keys()].sort()).toEqual(Object.keys(pins).sort());
    for (const tile of fresh) expect(arranged.get(tile.id)).toEqual(tile.position);
  });
});
