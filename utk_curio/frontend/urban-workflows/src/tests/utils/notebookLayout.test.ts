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
  notebookFlowProps,
  notebookHandleOffsets,
  notebookInputLabel,
  notebookLaneX,
  NOTEBOOK_BAR_WIDTH,
  NOTEBOOK_CELL_GAP,
  NOTEBOOK_CELL_HEIGHT,
  NOTEBOOK_CELL_WIDTH,
  NOTEBOOK_MARGIN,
  NOTEBOOK_SLIM_HEIGHT,
} from "../../utils/notebookLayout";

const pane = { width: 1600, top: 110, left: 56 };

describe("the column of cells", () => {
  test("cells stack in the order given, each the same size, a fixed gap apart", () => {
    const layout = layoutNotebook(
      [{ id: "a", slim: false }, { id: "b", slim: false }, { id: "c", slim: false }],
      pane,
    );
    const ys = ["a", "b", "c"].map((id) => layout.positions.get(id)!.y);
    expect(ys[0]).toBe(pane.top + NOTEBOOK_MARGIN);
    expect(ys[1] - ys[0]).toBe(NOTEBOOK_CELL_HEIGHT + NOTEBOOK_CELL_GAP);
    expect(ys[2] - ys[1]).toBe(NOTEBOOK_CELL_HEIGHT + NOTEBOOK_CELL_GAP);
    expect(new Set(["a", "b", "c"].map((id) => layout.positions.get(id)!.x)).size).toBe(1);
    expect(["a", "b", "c"].map((id) => layout.heights.get(id))).toEqual([
      NOTEBOOK_CELL_HEIGHT, NOTEBOOK_CELL_HEIGHT, NOTEBOOK_CELL_HEIGHT,
    ]);
    expect(layout.rows.get("c")).toBe(2);
  });

  test("the column and its bar are centered in a wide pane", () => {
    const layout = layoutNotebook([{ id: "a", slim: false }], pane);
    const span = NOTEBOOK_CELL_WIDTH + NOTEBOOK_BAR_WIDTH;
    expect(layout.columnX).toBe(Math.round((pane.width - span) / 2));
    expect(layout.barX).toBe(layout.columnX + NOTEBOOK_CELL_WIDTH);
  });

  test("a narrow pane keeps the column clear of the palette rail", () => {
    const layout = layoutNotebook([{ id: "a", slim: false }], { width: 900, top: 110, left: 56 });
    expect(layout.columnX).toBe(56 + NOTEBOOK_MARGIN);
  });

  test("an icon-only node takes a short row", () => {
    const layout = layoutNotebook([{ id: "merge", slim: true }, { id: "after", slim: false }], pane);
    expect(layout.heights.get("merge")).toBe(NOTEBOOK_SLIM_HEIGHT);
    expect(layout.positions.get("after")!.y - layout.positions.get("merge")!.y).toBe(
      NOTEBOOK_SLIM_HEIGHT + NOTEBOOK_CELL_GAP,
    );
  });

  test("the content runs past the last cell, so it scrolls clear of the window's edge", () => {
    const layout = layoutNotebook([{ id: "a", slim: false }], pane);
    expect(layout.contentHeight).toBeGreaterThan(layout.positions.get("a")!.y + NOTEBOOK_CELL_HEIGHT);
  });
});

describe("the dots on a cell's right edge", () => {
  const handles = [
    { id: "in", type: "target" as const },
    { id: "in_1", type: "target" as const },
    { id: "out", type: "source" as const },
  ];

  test("inputs go down from the top in circle order, the output sits at the bottom", () => {
    const offsets = notebookHandleOffsets(handles, NOTEBOOK_CELL_HEIGHT);
    expect(offsets.get("in")!).toBeLessThan(offsets.get("in_1")!);
    expect(offsets.get("in_1")!).toBeLessThan(NOTEBOOK_CELL_HEIGHT / 2);
    expect(offsets.get("out")!).toBeGreaterThan(NOTEBOOK_CELL_HEIGHT * 0.9);
  });

  test("the interaction dot sits halfway down, below every input", () => {
    const many = Array.from({ length: 14 }, (_, k) => ({ id: k === 0 ? "in" : `in_${k}`, type: "target" as const }));
    const offsets = notebookHandleOffsets(
      [...many, { id: "in/out", type: "source" }, { id: "out", type: "source" }],
      NOTEBOOK_CELL_HEIGHT,
    );
    expect(offsets.get("in/out")).toBe(NOTEBOOK_CELL_HEIGHT / 2);
    expect(offsets.get("in_13")!).toBeLessThan(NOTEBOOK_CELL_HEIGHT / 2);
  });

  test("a short row still fits five input circles above its output", () => {
    const inputs = ["in_0", "in_1", "in_2", "in_3", "in_4"].map((id) => ({ id, type: "target" as const }));
    const offsets = notebookHandleOffsets([...inputs, { id: "out", type: "source" }], NOTEBOOK_SLIM_HEIGHT);
    const tops = inputs.map((h) => offsets.get(h.id)!);
    expect(tops).toEqual([...tops].sort((a, b) => a - b));
    expect(tops[4]).toBeLessThan(offsets.get("out")!);
    expect(offsets.get("out")!).toBeLessThan(NOTEBOOK_SLIM_HEIGHT);
  });

  test("an input dot carries the number its chips use, or a named input's name", () => {
    expect(notebookInputLabel("in")).toBe("0");
    expect(notebookInputLabel("in_12")).toBe("12");
    expect(notebookInputLabel("in_points")).toBe("points");
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
