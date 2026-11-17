/**
 * What the browser shows on a canvas stays in sight, and React Flow's own
 * element stays at 0,0.
 *
 * `.react-flow` hides its overflow and React Flow draws a pan as its viewport's
 * transform, but the browser still scrolls the element to show what Tab
 * reaches past the canvas's right or bottom edge. React Flow 11 never scrolls
 * it back, so the dot grid, the pane and the zoom buttons stayed that far off
 * the window, and every fit drew the nodes that far off where it put them. And
 * the browser cannot scroll the element to a negative offset, so a node left
 * of the view or above it stayed out of sight when Tab reached it
 * (`test_canvas_wrapper_scroll_e2e.py` does both with Tab). Both canvases
 * spread the handlers on their React Flow (`reactFlowScroll.test.ts`).
 *
 * Drawn with React Flow itself, the handlers spread on it as the canvases
 * spread them. jsdom lays nothing out, so a node's box on the page is worked
 * out from the view and the element's scroll, as the browser lays it out,
 * under a menu bar 64 px tall and beside a rail 60 px wide.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { ReactFlow, ReactFlowProvider, useStoreApi, type Node, type NodeProps, type Viewport } from "reactflow";
import { panIntoSight, useFlowInSight, type Box } from "../../hook/useFlowInSight";

// jsdom polyfills React Flow needs (as in mainCanvasNodeDoubleClick).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

const WINDOW = { width: 1280, height: 720 };
const BAR_BOTTOM = 64;
const RAIL_RIGHT = 60;
/** The part of the window the rail and the bar leave in sight. */
const SIGHT: Box = { left: RAIL_RIGHT, top: BAR_BOTTOM, right: WINDOW.width, bottom: WINDOW.height };

/** A node with a box of its own that scrolls, as an editor or a table does. */
function Card({ id }: NodeProps) {
  return (
    <div className="nowheel nodrag" data-testid={`rows-${id}`} style={{ height: 40, overflow: "auto" }}>
      rows
    </div>
  );
}

const NODE_TYPES = { card: Card };

type Seen = {
  store?: ReturnType<typeof useStoreApi>;
  inSight?: ReturnType<typeof useFlowInSight>;
};

function Canvas({ nodes, view, moves, seen }: { nodes: Node[]; view: Viewport; moves?: boolean; seen: Seen }) {
  const inSight = useFlowInSight(moves);
  seen.store = useStoreApi();
  seen.inSight = inSight;
  return (
    <ReactFlow
      nodes={nodes}
      edges={[]}
      nodeTypes={NODE_TYPES}
      defaultViewport={view}
      {...inSight}
      proOptions={{ hideAttribution: true }}
    />
  );
}

function rect(left: number, top: number, width: number, height: number): DOMRect {
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) } as DOMRect;
}

/**
 * Draw a canvas of one node, *size* at *at*, beside the rail and under the bar,
 * React Flow's element filling the window. The node's box on the page follows
 * the view and the element's scroll, as the browser lays it out.
 */
function drawCanvas({ at, size = { width: 525, height: 350 }, view, moves }: {
  at: { x: number; y: number };
  size?: { width: number; height: number };
  view: Viewport;
  moves?: boolean;
}) {
  const seen: Seen = {};
  const nodes: Node[] = [{ id: "far", type: "card", position: at, data: {} }];
  const { container } = render(
    <ReactFlowProvider>
      <header data-curio-menu-bar="true" />
      <div id="tools-palette-dock" />
      <div style={{ width: WINDOW.width, height: WINDOW.height }}>
        <Canvas nodes={nodes} view={view} moves={moves} seen={seen} />
      </div>
    </ReactFlowProvider>,
  );
  const element = container.querySelector(".react-flow") as HTMLDivElement;
  const node = container.querySelector('.react-flow__node[data-id="far"]') as HTMLDivElement;
  element.getBoundingClientRect = () => rect(0, 0, WINDOW.width, WINDOW.height);
  (container.querySelector("[data-curio-menu-bar]") as HTMLElement).getBoundingClientRect = () =>
    rect(0, 0, WINDOW.width, BAR_BOTTOM);
  (container.querySelector("#tools-palette-dock") as HTMLElement).getBoundingClientRect = () =>
    rect(0, BAR_BOTTOM, RAIL_RIGHT, WINDOW.height - BAR_BOTTOM);
  node.getBoundingClientRect = () => {
    const [x, y, zoom] = seen.store!.getState().transform;
    return rect(
      x + at.x * zoom - element.scrollLeft,
      y + at.y * zoom - element.scrollTop,
      size.width * zoom,
      size.height * zoom,
    );
  };
  return {
    element,
    node,
    seen,
    view: () => seen.store!.getState().transform,
    scrolled: () => [element.scrollLeft, element.scrollTop],
    box: (): Box => {
      const r = node.getBoundingClientRect();
      return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    },
  };
}

/** Scroll *element* as the browser does to show something in it, and fire its scroll. */
function scrollBy(element: HTMLElement, across: number, down: number) {
  element.scrollLeft = across;
  element.scrollTop = down;
  fireEvent.scroll(element);
}

/** Focus *node* as Tab does, which the browser shows as the keyboard's, or as a click does. */
function focus(node: HTMLElement, by: "keyboard" | "click") {
  const matches = Element.prototype.matches;
  Object.defineProperty(node, "matches", {
    configurable: true,
    value(this: Element, selector: string) {
      return selector === ":focus-visible" ? by === "keyboard" : matches.call(this, selector);
    },
  });
  act(() => {
    node.focus();
  });
}

const inSight = (box: Box) =>
  box.left >= SIGHT.left && box.top >= SIGHT.top && box.right <= SIGHT.right && box.bottom <= SIGHT.bottom;

describe("a scroll of React Flow's element", () => {
  const VIEW = { x: 120, y: 80, zoom: 0.75 };
  const AT = { x: 2400, y: 0 };

  test("the canvas opens in its view, its element at 0,0", () => {
    const canvas = drawCanvas({ at: AT, view: VIEW });
    expect({ scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
      scrolled: [0, 0],
      view: [VIEW.x, VIEW.y, VIEW.zoom],
    });
  });

  test("is the same pan, and the element is back at 0,0", () => {
    const canvas = drawCanvas({ at: AT, view: VIEW });
    scrollBy(canvas.element, 370, 40);
    expect({ scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
      scrolled: [0, 0],
      view: [VIEW.x - 370, VIEW.y - 40, VIEW.zoom],
    });
  });

  test("leaves the node where the browser brought it", () => {
    const canvas = drawCanvas({ at: AT, view: VIEW });
    canvas.element.scrollLeft = 370;
    const shown = canvas.box();
    fireEvent.scroll(canvas.element);
    expect({ scrolled: canvas.scrolled(), box: canvas.box() }).toEqual({ scrolled: [0, 0], box: shown });
  });

  test("that putting the element back fires moves nothing", () => {
    const canvas = drawCanvas({ at: AT, view: VIEW });
    scrollBy(canvas.element, 370, 40);
    fireEvent.scroll(canvas.element);
    expect({ scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
      scrolled: [0, 0],
      view: [VIEW.x - 370, VIEW.y - 40, VIEW.zoom],
    });
  });

  test("where the view is held (the notebook view's), only puts the element back", () => {
    const canvas = drawCanvas({ at: AT, view: VIEW, moves: false });
    scrollBy(canvas.element, 370, 40);
    expect({ scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
      scrolled: [0, 0],
      view: [VIEW.x, VIEW.y, VIEW.zoom],
    });
  });

  test("inside a node is the node's own", () => {
    const canvas = drawCanvas({ at: AT, view: VIEW });
    const rows = screen.getByTestId("rows-far");
    scrollBy(rows, 0, 25);
    // Even one handed to the canvas's handler while React Flow's element is scrolled.
    canvas.element.scrollLeft = 30;
    act(() => {
      canvas.seen.inSight!.onScroll({ target: rows, currentTarget: canvas.element } as any);
    });
    expect({ rows: rows.scrollTop, scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
      rows: 25,
      scrolled: [30, 0],
      view: [VIEW.x, VIEW.y, VIEW.zoom],
    });
  });
});

describe("a node the keyboard reaches", () => {
  const VIEW = { x: 0, y: 0, zoom: 1 };

  test.each([
    ["left of the view", { x: -2400, y: 200 }],
    ["above the view", { x: 300, y: -2400 }],
    ["past the right edge", { x: 2400, y: 200 }],
    ["below the view", { x: 300, y: 2400 }],
  ])("%s is panned to the middle of the sight", (_where, at) => {
    const canvas = drawCanvas({ at, view: VIEW });
    focus(canvas.node, "keyboard");
    const box = canvas.box();
    expect({ scrolled: canvas.scrolled(), inSight: inSight(box) }).toEqual({ scrolled: [0, 0], inSight: true });
  });

  test("whose header is under the bar comes down below it, the least distance", () => {
    const canvas = drawCanvas({ at: { x: 300, y: -100 }, view: VIEW });
    focus(canvas.node, "keyboard");
    expect(canvas.box()).toEqual({ left: 300, top: BAR_BOTTOM, right: 825, bottom: BAR_BOTTOM + 350 });
  });

  test("under the rail comes out right of it", () => {
    const canvas = drawCanvas({ at: { x: 20, y: 200 }, view: VIEW });
    focus(canvas.node, "keyboard");
    expect(canvas.box()).toEqual({ left: RAIL_RIGHT, top: 200, right: RAIL_RIGHT + 525, bottom: 550 });
  });

  test("taller than the sight shows its header below the bar, after the browser's own scroll too", () => {
    const canvas = drawCanvas({ at: { x: 300, y: 2400 }, size: { width: 525, height: 1000 }, view: VIEW });
    focus(canvas.node, "keyboard");
    const panned = canvas.box();
    // The browser then scrolls the node it focused into view: one larger than
    // the window, its top to the window's top, under the bar.
    scrollBy(canvas.element, 0, panned.top);
    expect({ panned: panned.top, shown: canvas.box().top, scrolled: canvas.scrolled() }).toEqual({
      panned: BAR_BOTTOM,
      shown: BAR_BOTTOM,
      scrolled: [0, 0],
    });
  });

  test("already in sight stays where it is", () => {
    const canvas = drawCanvas({ at: { x: 300, y: 200 }, view: VIEW });
    focus(canvas.node, "keyboard");
    expect(canvas.view()).toEqual([0, 0, 1]);
  });

  test("by a click is left where it is", () => {
    const canvas = drawCanvas({ at: { x: -2400, y: 200 }, view: VIEW });
    focus(canvas.node, "click");
    expect(canvas.view()).toEqual([0, 0, 1]);
  });

  test("where the view is held (the notebook view's) is left where it is", () => {
    const canvas = drawCanvas({ at: { x: -2400, y: 200 }, view: VIEW, moves: false });
    focus(canvas.node, "keyboard");
    expect(canvas.view()).toEqual([0, 0, 1]);
  });
});

describe("panIntoSight", () => {
  const box = (left: number, top: number, width = 100, height = 50): Box => ({
    left, top, right: left + width, bottom: top + height,
  });

  test.each([
    ["in sight: nowhere", box(200, 200), [0, 0]],
    ["wholly left: to the middle across", box(-500, 200), [(60 + 1280) / 2 - (-500 + 50), 0]],
    ["wholly above: to the middle down", box(200, -500), [0, (64 + 720) / 2 - (-500 + 25)]],
    ["partly right: the least distance", box(1250, 200), [-70, 0]],
    ["partly under the bar: the least distance", box(200, 40), [0, 24]],
    ["wider than the sight: its left edge", box(-300, 200, 2000), [360, 0]],
    ["taller than the sight: its top edge", box(200, 300, 100, 900), [0, -236]],
  ] as const)("%s", (_case, given, moved) => {
    expect(panIntoSight(given, SIGHT)).toEqual(moved);
  });
});
