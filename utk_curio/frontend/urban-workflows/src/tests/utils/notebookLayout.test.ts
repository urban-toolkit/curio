/**
 * The notebook view's geometry (utils/notebookLayout): the column of cells,
 * the dots on each cell's right edge, the lanes the connections take in the
 * bar, the path each draws, and the React Flow settings that turn the canvas
 * into a scrolling page.
 */
import {
  assignNotebookLanes,
  layoutNotebook,
  notebookArcPath,
  notebookCellMinHeight,
  notebookFlowProps,
  notebookHandlePlaces,
  notebookInputLabel,
  notebookLaneX,
  NOTEBOOK_BAR_WIDTH,
  NOTEBOOK_CELL_GAP,
  NOTEBOOK_DOT_SIZE,
  NOTEBOOK_MARGIN,
  NOTEBOOK_MIN_CELL_WIDTH,
  NOTEBOOK_UNMEASURED_HEIGHT,
  notebookOutputBox,
  graphEditGates,
  type NotebookDotPlace,
} from "../../utils/notebookLayout";

const pane = { width: 1600, top: 110, left: 56 };

describe("the column of cells", () => {
  test("cells stack in the order given, each as tall as it was measured, 24px apart", () => {
    const layout = layoutNotebook(
      [{ id: "a", height: 180 }, { id: "b", height: 612 }, { id: "c", height: 95 }],
      pane,
    );
    const ys = ["a", "b", "c"].map((id) => layout.positions.get(id)!.y);
    expect(NOTEBOOK_CELL_GAP).toBe(24);
    expect(ys[0]).toBe(pane.top + NOTEBOOK_MARGIN);
    expect(ys[1] - ys[0]).toBe(180 + NOTEBOOK_CELL_GAP);
    expect(ys[2] - ys[1]).toBe(612 + NOTEBOOK_CELL_GAP);
    expect(new Set(["a", "b", "c"].map((id) => layout.positions.get(id)!.x)).size).toBe(1);
    expect(layout.rows.get("c")).toBe(2);
  });

  test("a cell that grows moves every cell below it by the same amount", () => {
    const before = layoutNotebook([{ id: "a", height: 200 }, { id: "b", height: 300 }, { id: "c", height: 300 }], pane);
    const after = layoutNotebook([{ id: "a", height: 200 }, { id: "b", height: 455 }, { id: "c", height: 300 }], pane);
    expect(after.positions.get("a")).toEqual(before.positions.get("a"));
    expect(after.positions.get("b")).toEqual(before.positions.get("b"));
    expect(after.positions.get("c")!.y - before.positions.get("c")!.y).toBe(155);
    expect(after.contentHeight - before.contentHeight).toBe(155);
  });

  test("a cell React Flow has not measured yet counts as 240px", () => {
    expect(NOTEBOOK_UNMEASURED_HEIGHT).toBe(240);
    const layout = layoutNotebook([{ id: "new" }, { id: "after", height: 100 }, { id: "last", height: null }], pane);
    expect(layout.positions.get("after")!.y - layout.positions.get("new")!.y).toBe(
      NOTEBOOK_UNMEASURED_HEIGHT + NOTEBOOK_CELL_GAP,
    );
    expect(layout.positions.get("last")!.y - layout.positions.get("after")!.y).toBe(100 + NOTEBOOK_CELL_GAP);
  });

  test("cells span the page from its left margin to the bar at its right edge", () => {
    const wide = { width: 1600, top: 110, left: 0 };
    const layout = layoutNotebook([{ id: "a", height: 300 }], wide);
    expect(layout.columnX).toBe(NOTEBOOK_MARGIN);
    expect(layout.barX).toBe(wide.width - NOTEBOOK_BAR_WIDTH);
    expect(layout.cellWidth).toBe(layout.barX - layout.columnX);
    expect(layout.positions.get("a")!.x).toBe(NOTEBOOK_MARGIN);
  });

  test("anything fixed over the page's left edge is cleared", () => {
    const layout = layoutNotebook([{ id: "a", height: 300 }], { width: 900, top: 110, left: 56 });
    expect(layout.columnX).toBe(56 + NOTEBOOK_MARGIN);
    expect(layout.barX).toBe(900 - NOTEBOOK_BAR_WIDTH);
  });

  test("on a narrow page a cell keeps its least width, and the bar moves out past it", () => {
    const layout = layoutNotebook([{ id: "a", height: 300 }], { width: 500, top: 110, left: 0 });
    expect(layout.cellWidth).toBe(NOTEBOOK_MIN_CELL_WIDTH);
    expect(layout.barX).toBe(NOTEBOOK_MARGIN + NOTEBOOK_MIN_CELL_WIDTH);
  });

  test("the content runs past the last cell, so it scrolls clear of the window's edge", () => {
    const layout = layoutNotebook([{ id: "a", height: 300 }, { id: "b", height: 410 }], pane);
    expect(layout.contentHeight).toBeGreaterThan(layout.positions.get("b")!.y + 410);
  });
});

/**
 * Where a dot's center lands in a cell of this height. React Flow centers a
 * right-side handle on its `top` (`translate(0, -50%)`), so a dot anchored to
 * the bottom has its center one dot above its `bottom`.
 */
function centerOf(place: NotebookDotPlace, height: number): number {
  if (place.top === "50%") return height / 2;
  if (place.top === "auto") return height - place.bottom - NOTEBOOK_DOT_SIZE;
  return place.top;
}

describe("the dots on a cell's right edge", () => {
  const handles = [
    { id: "in", type: "target" as const },
    { id: "in_1", type: "target" as const },
    { id: "out", type: "source" as const },
  ];

  test("inputs sit at fixed offsets from the top, in circle order", () => {
    const places = notebookHandlePlaces(handles);
    const top = (id: string) => (places.get(id) as { top: number }).top;
    expect(typeof top("in")).toBe("number");
    expect(top("in")).toBeLessThan(top("in_1"));
    // The same offsets whatever the cell's height: they do not move as it grows.
    expect(notebookHandlePlaces(handles).get("in_1")).toEqual(places.get("in_1"));
  });

  test("the output is anchored to the bottom, so it follows the cell as it grows", () => {
    const out = notebookHandlePlaces(handles).get("out")!;
    expect(out.top).toBe("auto");
    for (const height of [200, 800]) {
      const center = centerOf(out, height);
      expect(center).toBeGreaterThan(height - 60);
      expect(center).toBeLessThan(height);
    }
  });

  test("the interaction dot sits halfway down", () => {
    const places = notebookHandlePlaces([...handles, { id: "in/out", type: "source" }]);
    expect(places.get("in/out")).toEqual({ top: "50%" });
  });

  test("several outputs stack up from the bottom", () => {
    const places = notebookHandlePlaces([
      { id: "out", type: "source" },
      { id: "out_1", type: "source" },
    ]);
    expect(centerOf(places.get("out_1")!, 400)).toBeLessThan(centerOf(places.get("out")!, 400));
  });

  test("a cell is at least tall enough for its dots, none overlapping", () => {
    const cases = [
      [],
      [{ id: "out", type: "source" as const }],
      handles,
      [...handles, { id: "in/out", type: "source" as const }],
      [
        ...Array.from({ length: 14 }, (_, k) => ({ id: k === 0 ? "in" : `in_${k}`, type: "target" as const })),
        { id: "in/out", type: "source" as const },
        { id: "out", type: "source" as const },
        { id: "out_1", type: "source" as const },
      ],
    ];
    for (const list of cases) {
      const height = notebookCellMinHeight(list);
      const places = notebookHandlePlaces(list);
      const centers = list.map((h) => centerOf(places.get(h.id)!, height));
      for (const center of centers) {
        expect(center).toBeGreaterThanOrEqual(NOTEBOOK_DOT_SIZE / 2);
        expect(center).toBeLessThanOrEqual(height - NOTEBOOK_DOT_SIZE / 2);
      }
      const sorted = [...centers].sort((a, b) => a - b);
      for (let k = 1; k < sorted.length; k += 1) {
        expect(sorted[k] - sorted[k - 1]).toBeGreaterThanOrEqual(NOTEBOOK_DOT_SIZE);
      }
    }
  });

  test("more inputs need a taller cell", () => {
    const inputs = (n: number) => Array.from({ length: n }, (_, k) => ({ id: `in_${k}`, type: "target" as const }));
    const out = { id: "out", type: "source" as const };
    expect(notebookCellMinHeight([...inputs(12), out])).toBeGreaterThan(notebookCellMinHeight([...inputs(2), out]));
  });

  test("an input dot carries the number its chips use, or a named input's name", () => {
    expect(notebookInputLabel("in")).toBe("0");
    expect(notebookInputLabel("in_12")).toBe("12");
    expect(notebookInputLabel("in_points")).toBe("points");
  });
});

describe("the height of a cell's output", () => {
  test("a chart draws in a definite 320px, an Autark map or plot and a scenario comparison in 400px", () => {
    expect(notebookOutputBox("curio.builtin/vis-vega@1")).toEqual({ height: 320, overflow: "auto" });
    expect(notebookOutputBox("curio.builtin/autk-grammar")).toEqual({ height: 400 });
    expect(notebookOutputBox("curio.builtin/compare-scenarios@1")).toEqual({ height: 400 });
  });

  test("a table, a summary or a control takes its own height up to 360px", () => {
    for (const kind of ["data-pool", "vis-simple", "data-summary", "parameter", "spatial-join", "data-export"]) {
      expect(notebookOutputBox(`curio.builtin/${kind}@1`)).toEqual({ maxHeight: 360, overflow: "auto" });
    }
  });

  test("anything else, made to fill a node, gets a definite 360px", () => {
    expect(notebookOutputBox("acme.tools/heatmap@1")).toEqual({ height: 360, overflow: "auto" });
  });
});

describe("the lanes in the bar", () => {
  const rows = new Map([["a", 0], ["b", 1], ["c", 2], ["d", 3]]);

  test("a connection inside a longer one takes the inner lane", () => {
    const { lanes, count } = assignNotebookLanes(
      [
        { id: "long", source: "a", target: "d" },
        { id: "short", source: "b", target: "c" },
      ],
      rows,
    );
    expect(lanes.get("short")).toBe(0);
    expect(lanes.get("long")).toBe(1);
    expect(count).toBe(2);
  });

  test("connections that do not overlap share a lane", () => {
    const { lanes, count } = assignNotebookLanes(
      [
        { id: "ab", source: "a", target: "b" },
        { id: "cd", source: "c", target: "d" },
        { id: "bc", source: "b", target: "c" },
      ],
      rows,
    );
    expect([lanes.get("ab"), lanes.get("bc"), lanes.get("cd")]).toEqual([0, 0, 0]);
    expect(count).toBe(1);
  });

  test("two connections out of one cell never share a lane", () => {
    const { lanes } = assignNotebookLanes(
      [
        { id: "to-c", source: "a", target: "c" },
        { id: "to-d", source: "a", target: "d" },
      ],
      rows,
    );
    expect(lanes.get("to-c")).not.toBe(lanes.get("to-d"));
  });

  test("a connection to a cell not laid out gets no lane", () => {
    const { lanes } = assignNotebookLanes([{ id: "gone", source: "a", target: "zzz" }], rows);
    expect(lanes.has("gone")).toBe(false);
  });

  test("however many lanes there are, every one stays inside the bar", () => {
    const barX = 1000;
    for (const count of [1, 5, 40]) {
      for (let lane = 0; lane < count; lane += 1) {
        const x = notebookLaneX(barX, lane, count);
        expect(x).toBeGreaterThan(barX);
        expect(x).toBeLessThan(barX + NOTEBOOK_BAR_WIDTH);
      }
    }
    expect(notebookLaneX(barX, 1, 3)).toBeGreaterThan(notebookLaneX(barX, 0, 3));
  });
});

describe("the path a connection draws in the bar", () => {
  test("out from the source dot, down its lane, back in to the target dot", () => {
    const [path, labelX, labelY] = notebookArcPath(900, 600, 900, 1200, 960);
    expect(path.startsWith("M 900,600")).toBe(true);
    expect(path.endsWith("L 900,1200")).toBe(true);
    expect(path).toContain("960,");
    expect(labelX).toBe(960);
    expect(labelY).toBe(900);
  });

  test("an upward connection runs up its lane", () => {
    const [path] = notebookArcPath(900, 1200, 900, 600, 960);
    expect(path.startsWith("M 900,1200")).toBe(true);
    expect(path.endsWith("L 900,600")).toBe(true);
  });
});

describe("where the graph is changed", () => {
  test("nodes are added and connected on the canvas", () => {
    expect(graphEditGates({ notebookOn: false, sharedView: false })).toEqual({ connect: true, drop: true });
  });

  test("the notebook view adds and connects nothing", () => {
    expect(graphEditGates({ notebookOn: true, sharedView: false })).toEqual({ connect: false, drop: false });
  });

  test("a shared viewer changes nothing in either view", () => {
    expect(graphEditGates({ notebookOn: false, sharedView: true })).toEqual({ connect: false, drop: false });
    expect(graphEditGates({ notebookOn: true, sharedView: true })).toEqual({ connect: false, drop: false });
  });
});

describe("the React Flow settings of the notebook view", () => {
  const props = notebookFlowProps(1280, 4000);

  test("hold the zoom at 1 and the view on the pane, so the page scrolls instead", () => {
    expect(props.minZoom).toBe(1);
    expect(props.maxZoom).toBe(1);
    expect(props.translateExtent).toEqual([[0, 0], [1280, 4000]]);
    expect(props.preventScrolling).toBe(false);
    expect(props.zoomOnScroll).toBe(false);
    expect(props.zoomOnPinch).toBe(false);
    expect(props.zoomOnDoubleClick).toBe(false);
    expect(props.panOnScroll).toBe(false);
    expect(props.panOnDrag).toBe(false);
    expect(props.nodesDraggable).toBe(false);
  });

  test("leave the shared view's gates to the canvas", () => {
    // Spread over the canvas's props, they must not touch what a shared
    // viewer is refused: connecting, deleting, dropping.
    for (const gate of ["onConnect", "nodesConnectable", "edgesUpdatable", "deleteKeyCode", "elementsSelectable", "onDrop"]) {
      expect(Object.keys(props)).not.toContain(gate);
    }
  });
});
