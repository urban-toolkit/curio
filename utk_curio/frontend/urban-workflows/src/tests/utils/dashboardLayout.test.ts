/**
 * The two decisions the dashboard page makes before it renders anything.
 *
 * `prepareDashboardNodes` turns a loaded dataflow into tiles. Three properties
 * matter and none of them are visible from the page itself:
 *
 *  - the canvas coordinates survive, because `TrillGenerator` saves
 *    `data.workflowPosition` in preference to `position`, so a save made from
 *    the dashboard must not write tile positions over the authored layout;
 *  - an unpinned node stays MOUNTED. React Flow's own `hidden` unmounts the
 *    component, and an unpinned Data Pool or Merge is exactly what re-derives a
 *    tile's data from the restored outputs, so unmounting it empties the tile it
 *    was feeding;
 *  - it is pure and idempotent, because a load can run it more than once.
 *
 * `dashboardSourceNodeIds` decides whose outputs get saved to the Data Catalog,
 * which is the whole reason a dashboard can draw without a run. Getting it wrong
 * is quiet in both directions: too narrow and the tile is empty, too wide and
 * the user's catalog fills with datasets nothing reads.
 */
import {
  DASHBOARD_TILE_DEFAULT_HEIGHT,
  DASHBOARD_TILE_DEFAULT_WIDTH,
  DASHBOARD_TILE_DRAG_HANDLE,
  dashboardSourceNodeIds,
  prepareDashboardNodes,
} from "../../utils/dashboardLayout";
import { NodeType } from "../../constants";

function node(id: string, nodeType: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "__curioUniversalNode",
    position: { x: 10, y: 20 },
    data: { nodeId: id, nodeType, ...extra },
  } as any;
}

function edge(source: string, target: string) {
  return { id: `${source}-${target}`, source, target } as any;
}

const RENDER_SPEC = JSON.stringify({ map: { layerRefs: [] } });
const COMPUTE_SPEC = JSON.stringify({ compute: [{ shader: "x" }] });
const DATA_SPEC = JSON.stringify({ data: [{ type: "osm" }] });

describe("the automatic layout leaves room for the tiles it places", () => {
  // A tile is drawn at `dashboardWidth`, or at the dashboard's own default when
  // nobody has resized it. The layout used to advance columns by a single fixed
  // pitch that was narrower than either, so two pinned tiles in adjacent columns
  // were laid down on top of each other and the owner had to drag them apart
  // before the dashboard could be read at all.
  test("two columns are at least a tile apart", () => {
    const nodes = [
      node("src", NodeType.COMPUTATION_ANALYSIS, { dashboardPinned: true }),
      node("chart", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];
    const edges = [edge("src", "chart")];

    const prepared = prepareDashboardNodes(nodes, edges, { src: true, chart: true });
    const src = prepared.nodes.find((n) => n.id === "src")!;
    const chart = prepared.nodes.find((n) => n.id === "chart")!;

    expect(Math.abs(chart.position.x - src.position.x)).toBeGreaterThanOrEqual(
      DASHBOARD_TILE_DEFAULT_WIDTH,
    );
  });

  test("a column is as wide as its widest tile, not as the default", () => {
    const wide = 1400;
    const nodes = [
      node("src", NodeType.COMPUTATION_ANALYSIS, { dashboardPinned: true, dashboardWidth: wide }),
      node("chart", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];
    const edges = [edge("src", "chart")];

    const prepared = prepareDashboardNodes(nodes, edges, { src: true, chart: true });
    const src = prepared.nodes.find((n) => n.id === "src")!;
    const chart = prepared.nodes.find((n) => n.id === "chart")!;

    expect(chart.position.x - src.position.x).toBeGreaterThanOrEqual(wide);
  });

  test("tiles stacked in one column clear each other vertically", () => {
    const nodes = [
      node("a", NodeType.VIS_VEGA, { dashboardPinned: true }),
      node("b", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];

    const prepared = prepareDashboardNodes(nodes, [], { a: true, b: true });
    const ys = prepared.nodes
      .filter((n) => n.id === "a" || n.id === "b")
      .map((n) => n.position.y)
      .sort((x, y) => x - y);

    expect(ys[1] - ys[0]).toBeGreaterThanOrEqual(DASHBOARD_TILE_DEFAULT_HEIGHT);
  });

  test("a saved tile position still wins over the automatic one", () => {
    const nodes = [
      node("a", NodeType.VIS_VEGA, { dashboardPinned: true, dashboardX: 400, dashboardY: 120 }),
    ];

    const prepared = prepareDashboardNodes(nodes, [], { a: true });

    expect(prepared.nodes[0].position).toEqual({ x: 400, y: 120 });
  });
});

describe("prepareDashboardNodes", () => {
  test("it stamps the canvas position, so a save cannot overwrite it", () => {
    const nodes = [node("a", NodeType.VIS_VEGA, { dashboardPinned: true })];

    const prepared = prepareDashboardNodes(nodes, [], { a: true });

    expect(prepared.nodes[0].data.workflowPosition).toEqual({ x: 10, y: 20 });
  });

  test("a position already stamped is left alone", () => {
    const nodes = [node("a", NodeType.VIS_VEGA, {
      dashboardPinned: true,
      workflowPosition: { x: 1, y: 2 },
    })];

    const prepared = prepareDashboardNodes(nodes, [], { a: true });

    expect(prepared.nodes[0].data.workflowPosition).toEqual({ x: 1, y: 2 });
  });

  test("a pinned tile takes its saved slot and can be dragged by its title", () => {
    const nodes = [node("a", NodeType.VIS_VEGA, {
      dashboardPinned: true, dashboardX: 400, dashboardY: 120,
    })];

    const [tile] = prepareDashboardNodes(nodes, [], { a: true }).nodes;

    expect(tile.position).toEqual({ x: 400, y: 120 });
    expect(tile.style).toBeUndefined();
    expect(tile.dragHandle).toBe(DASHBOARD_TILE_DRAG_HANDLE);
  });

  test("a tile leaves the page's lock in charge of whether it moves", () => {
    // React Flow prefers a node's own flag over the canvas-wide one, so a tile
    // marked draggable would be movable while the layout is locked - which is
    // the state every viewer of a shared dashboard is in.
    const nodes = [node("a", NodeType.VIS_VEGA, { dashboardPinned: true })];

    const [tile] = prepareDashboardNodes(nodes, [], { a: true }).nodes as any[];

    expect(tile.draggable).toBeUndefined();
    expect(tile.selectable).toBeUndefined();
  });

  test("a pinned tile with no saved slot is laid out automatically", () => {
    const nodes = [
      node("a", NodeType.COMPUTATION_ANALYSIS, { dashboardPinned: true }),
      node("b", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];
    nodes[1].position = { x: 10, y: 400 };

    const prepared = prepareDashboardNodes(nodes, [edge("a", "b")], { a: true, b: true });

    const positions = prepared.nodes.map((n: any) => n.position);
    expect(positions).not.toContainEqual({ x: 10, y: 400 });
    // Laid out left to right along the graph, so a chain reads as a chain.
    const byId = new Map(prepared.nodes.map((n: any) => [n.id, n.position]));
    expect((byId.get("b") as any).x).toBeGreaterThan((byId.get("a") as any).x);
  });

  test("an unpinned node is hidden with display:none, never unmounted", () => {
    const nodes = [
      node("pool", NodeType.DATA_POOL),
      node("chart", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];

    const prepared = prepareDashboardNodes(nodes, [edge("pool", "chart")], { chart: true });

    const pool = prepared.nodes.find((n: any) => n.id === "pool") as any;
    // `hidden: true` would take the component out of the tree with it, and the
    // pool is what hands the chart its rows.
    expect(pool.hidden).toBeUndefined();
    expect(pool.style.display).toBe("none");
    expect(pool.draggable).toBe(false);
    expect(pool.selectable).toBe(false);
    // Its canvas position is untouched: hidden, not moved.
    expect(pool.position).toEqual({ x: 10, y: 20 });
  });

  test("every edge is hidden", () => {
    const prepared = prepareDashboardNodes(
      [node("a", NodeType.COMPUTATION_ANALYSIS), node("b", NodeType.VIS_VEGA, { dashboardPinned: true })],
      [edge("a", "b")],
      { b: true },
    );

    expect(prepared.edges.every((e: any) => e.hidden)).toBe(true);
  });

  test("with nothing pinned, nothing is shown", () => {
    const nodes = [node("a", NodeType.VIS_VEGA), node("b", NodeType.DATA_POOL)];

    const prepared = prepareDashboardNodes(nodes, [], {});

    expect(prepared.nodes.every((n: any) => n.style.display === "none")).toBe(true);
  });

  test("it does not mutate what it is given", () => {
    const nodes = [node("a", NodeType.VIS_VEGA, { dashboardPinned: true })];
    const edges = [edge("a", "a")];
    const snapshot = JSON.parse(JSON.stringify({ nodes, edges }));

    prepareDashboardNodes(nodes, edges, { a: true });

    expect(JSON.parse(JSON.stringify({ nodes, edges }))).toEqual(snapshot);
  });

  test("running it twice changes nothing more", () => {
    const nodes = [
      node("a", NodeType.COMPUTATION_ANALYSIS),
      node("b", NodeType.VIS_VEGA, { dashboardPinned: true, dashboardX: 5, dashboardY: 6 }),
    ];
    const edges = [edge("a", "b")];

    const once = prepareDashboardNodes(nodes, edges, { b: true });
    const twice = prepareDashboardNodes(once.nodes, once.edges, { b: true });

    expect(twice.nodes.map((n: any) => n.position)).toEqual(once.nodes.map((n: any) => n.position));
    expect(twice.nodes.map((n: any) => n.data.workflowPosition))
      .toEqual(once.nodes.map((n: any) => n.data.workflowPosition));
  });
});

describe("dashboardSourceNodeIds", () => {
  test("the producer behind a pinned chart", () => {
    const nodes = [
      node("py", NodeType.COMPUTATION_ANALYSIS),
      node("chart", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];

    expect([...dashboardSourceNodeIds(nodes, [edge("py", "chart")])]).toEqual(["py"]);
  });

  test("a Data Pool is walked through, not saved", () => {
    // The pool re-derives its table from its input on every load, so saving its
    // passthrough would duplicate the producer's dataset under another name.
    const nodes = [
      node("py", NodeType.COMPUTATION_ANALYSIS),
      node("pool", NodeType.DATA_POOL),
      node("chart", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];

    const sources = dashboardSourceNodeIds(nodes, [edge("py", "pool"), edge("pool", "chart")]);

    expect([...sources]).toEqual(["py"]);
  });

  test("both branches of a merge", () => {
    const nodes = [
      node("x", NodeType.DATA_LOADING),
      node("y", NodeType.DATA_LOADING),
      node("merge", NodeType.MERGE_FLOW),
      node("pool", NodeType.DATA_POOL),
      node("chart", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];

    const sources = dashboardSourceNodeIds(nodes, [
      edge("x", "merge"), edge("y", "merge"), edge("merge", "pool"), edge("pool", "chart"),
    ]);

    expect([...sources].sort()).toEqual(["x", "y"]);
  });

  test("the walk stops at the first producer, not the top of the chain", () => {
    // `b` is what the chart reads; `a` is already consumed and saving it would
    // record a dataset nothing on the dashboard asks for.
    const nodes = [
      node("a", NodeType.COMPUTATION_ANALYSIS),
      node("b", NodeType.COMPUTATION_ANALYSIS),
      node("chart", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];

    const sources = dashboardSourceNodeIds(nodes, [edge("a", "b"), edge("b", "chart")]);

    expect([...sources]).toEqual(["b"]);
  });

  test("an Autark map tile reads its compute node, which is a source", () => {
    const nodes = [
      node("load", NodeType.AUTK_GRAMMAR, { code: DATA_SPEC }),
      node("compute", NodeType.AUTK_GRAMMAR, { code: COMPUTE_SPEC }),
      node("pool", NodeType.DATA_POOL),
      node("map", NodeType.AUTK_GRAMMAR, { code: RENDER_SPEC, dashboardPinned: true }),
    ];

    const sources = dashboardSourceNodeIds(nodes, [
      edge("load", "compute"), edge("compute", "pool"), edge("pool", "map"),
    ]);

    // Not `load`: the compute node's layers are what the map draws, and its
    // dataset is what a reload restores.
    expect([...sources]).toEqual(["compute"]);
  });

  test("an Autark node that draws is walked through like any other view", () => {
    const nodes = [
      node("load", NodeType.AUTK_GRAMMAR, { code: DATA_SPEC }),
      node("map1", NodeType.AUTK_GRAMMAR, { code: RENDER_SPEC }),
      node("map2", NodeType.AUTK_GRAMMAR, { code: RENDER_SPEC, dashboardPinned: true }),
    ];

    const sources = dashboardSourceNodeIds(nodes, [edge("load", "map1"), edge("map1", "map2")]);

    expect([...sources]).toEqual(["load"]);
  });

  test("a versioned node type is recognised", () => {
    // Palette-dragged nodes carry `@1`; comparing the raw string silently
    // matches nothing (#169).
    const nodes = [
      node("py", "curio.builtin/computation-analysis@1"),
      node("pool", "curio.builtin/data-pool@1"),
      node("chart", "curio.builtin/vis-vega@1", { dashboardPinned: true }),
    ];

    const sources = dashboardSourceNodeIds(nodes, [edge("py", "pool"), edge("pool", "chart")]);

    expect([...sources]).toEqual(["py"]);
  });

  test("a pinned node's own output is not in the set", () => {
    // What a tile draws comes from its input. A node rendering its own run
    // output (a code node's stdout) has nothing a dataset could restore.
    const nodes = [node("py", NodeType.COMPUTATION_ANALYSIS, { dashboardPinned: true })];

    expect([...dashboardSourceNodeIds(nodes, [])]).toEqual([]);
  });

  test("nothing pinned means nothing to save", () => {
    const nodes = [node("py", NodeType.COMPUTATION_ANALYSIS), node("chart", NodeType.VIS_VEGA)];

    expect(dashboardSourceNodeIds(nodes, [edge("py", "chart")]).size).toBe(0);
  });

  test("a cycle terminates", () => {
    const nodes = [
      node("pool1", NodeType.DATA_POOL),
      node("pool2", NodeType.DATA_POOL),
      node("chart", NodeType.VIS_VEGA, { dashboardPinned: true }),
    ];

    const sources = dashboardSourceNodeIds(nodes, [
      edge("pool1", "pool2"), edge("pool2", "pool1"), edge("pool2", "chart"),
    ]);

    expect([...sources]).toEqual([]);
  });

  test("an edge to a node that is not in the graph is ignored", () => {
    const nodes = [node("chart", NodeType.VIS_VEGA, { dashboardPinned: true })];

    expect(dashboardSourceNodeIds(nodes, [edge("ghost", "chart")]).size).toBe(0);
  });
});
