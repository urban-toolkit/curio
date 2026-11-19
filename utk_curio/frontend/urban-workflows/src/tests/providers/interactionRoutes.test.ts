/**
 * Where an interaction edge carries a selection (providers/flow/interactionRoutes):
 * each edge carries selections both ways, so it is two routes, each out of the
 * node at one end and into the node at the other. The handle at each end says
 * how much: a node's own handle (`in/out`) sends every view's selects and
 * delivers to the whole node; a view's (`in/out@<id>`) sends that view's
 * selection alone and delivers to that view alone. The module is loaded in each
 * test, so a checkout without it fails each test on its own.
 */
import { NodeType, VisInteractionType } from "../../constants";

type Route = { from: string; fromView: string | null; to: string; toView: string | null };

const routes = () =>
  require("../../providers/flow/interactionRoutes") as {
    routesOfEdge: (edge: unknown) => [Route, Route];
    interactionRoutes: (edges: readonly unknown[]) => Map<string, Route>;
    routeKey: (route: Route) => string;
    deliveriesOver: (sender: string, details: unknown, over: readonly Route[]) => any[];
    sameDelivery: (a: unknown, b: unknown) => boolean;
  };

/** An interaction edge as a saved dataflow holds it, a node's own handle at an end with no view. */
const edge = (id: string, source: string, sourceView: string | null, target: string, targetView: string | null) => ({
  id,
  source,
  target,
  sourceHandle: sourceView === null ? "in/out" : `in/out@${sourceView}`,
  targetHandle: targetView === null ? "in/out" : `in/out@${targetView}`,
  type: "Interaction",
});

const autk = (data: number[], priority: number, layerRef = "input_0") => ({
  type: VisInteractionType.POINT, data, priority, source: NodeType.AUTK_GRAMMAR, layerRef,
});

/** What a node of a map `city` and a plot `heights` sends after a brush on the plot, a pick on the map before it. */
const VIEWS = { "autk_selection@city": autk([2], 0), "autk_selection@heights": autk([0, 1], 1) };
/** A Vega-Lite chart's click. */
const PICK = { pick: { type: VisInteractionType.POINT, data: [1], priority: 1, source: NodeType.VIS_VEGA } };

describe("an interaction edge is two routes", () => {
  test("between two nodes' own handles, each way, of no view", () => {
    expect(routes().routesOfEdge(edge("e", "a", null, "b", null))).toEqual([
      { from: "a", fromView: null, to: "b", toView: null },
      { from: "b", fromView: null, to: "a", toView: null },
    ]);
  });

  test("a view's handle at one end: out of that view one way, into it the other", () => {
    expect(routes().routesOfEdge(edge("e", "views", "heights", "chart", null))).toEqual([
      { from: "views", fromView: "heights", to: "chart", toView: null },
      { from: "chart", fromView: null, to: "views", toView: "heights" },
    ]);
  });

  test("the routes of a dataflow's edges: each once, and none of a data edge", () => {
    const found = routes().interactionRoutes([
      edge("own", "a", null, "b", null),
      edge("again", "a", null, "b", null),
      edge("view", "a", "city", "b", null),
      { id: "data", source: "a", target: "b", sourceHandle: "out", targetHandle: "in" },
    ]);
    expect([...found.values()]).toEqual([
      { from: "a", fromView: null, to: "b", toView: null },
      { from: "b", fromView: null, to: "a", toView: null },
      { from: "a", fromView: "city", to: "b", toView: null },
      { from: "b", fromView: null, to: "a", toView: "city" },
    ]);
    expect([...found.keys()]).toEqual([...found.values()].map(routes().routeKey));
  });
});

describe("what a route delivers", () => {
  const route = (fromView: string | null, toView: string | null): Route => ({ from: "views", fromView, to: "chart", toView });

  test("out of a node's own handle into another's: every select as it was sent, as before", () => {
    expect(routes().deliveriesOver("views", VIEWS, [route(null, null)])).toEqual([
      { nodeId: "views", details: VIEWS, priority: 1 },
    ]);
    expect(routes().deliveriesOver("chart", PICK, [{ from: "chart", fromView: null, to: "views", toView: null }])).toEqual([
      { nodeId: "chart", details: PICK, priority: 1 },
    ]);
  });

  test("out of a view: that view's select alone, at priority 1 though another view's is newer", () => {
    expect(routes().deliveriesOver("views", VIEWS, [route("city", null)])).toEqual([
      { nodeId: "views", details: { "autk_selection@city": { ...VIEWS["autk_selection@city"], priority: 1 } }, priority: 1, fromView: "city" },
    ]);
  });

  test("into a view: to that view alone, which the delivery names", () => {
    expect(routes().deliveriesOver("chart", PICK, [{ from: "chart", fromView: null, to: "views", toView: "heights" }])).toEqual([
      { nodeId: "chart", details: PICK, priority: 1, toView: "heights" },
    ]);
  });

  test("nothing out of a view that holds no select of its own, nor out of a view of a node that has none", () => {
    expect(routes().deliveriesOver("views", VIEWS, [route("parks", null)])).toEqual([]);
    expect(routes().deliveriesOver("chart", PICK, [{ from: "chart", fromView: "heights", to: "views", toView: null }])).toEqual([]);
  });

  test("out of any view of a node of one view: its one select", () => {
    const one = { autk_selection: autk([1], 1) };
    expect(routes().deliveriesOver("views", one, [route("city", null)])).toEqual([
      { nodeId: "views", details: one, priority: 1, fromView: "city" },
    ]);
  });

  test("two routes that deliver the same selects to the same view deliver them once; to two views, twice", () => {
    const heights = { "autk_selection@heights": autk([0, 1], 1) };
    expect(routes().deliveriesOver("views", heights, [route(null, null), route("heights", null)])).toEqual([
      { nodeId: "views", details: heights, priority: 1 },
    ]);
    expect(routes().deliveriesOver("chart", PICK, [
      { from: "chart", fromView: null, to: "views", toView: "city" },
      { from: "chart", fromView: null, to: "views", toView: "heights" },
    ])).toEqual([
      { nodeId: "chart", details: PICK, priority: 1, toView: "city" },
      { nodeId: "chart", details: PICK, priority: 1, toView: "heights" },
    ]);
  });

  test("a delivery is the same as another from the same node, of the same selects, to the same view", () => {
    const one = { nodeId: "views", details: VIEWS, priority: 1 };
    expect(routes().sameDelivery(one, { ...one, details: JSON.parse(JSON.stringify(VIEWS)) })).toBe(true);
    expect(routes().sameDelivery(one, { ...one, fromView: "city" })).toBe(true);
    expect(routes().sameDelivery(one, { ...one, toView: "city" })).toBe(false);
    expect(routes().sameDelivery(one, { ...one, nodeId: "other" })).toBe(false);
    expect(routes().sameDelivery(one, { ...one, details: PICK })).toBe(false);
  });
});
