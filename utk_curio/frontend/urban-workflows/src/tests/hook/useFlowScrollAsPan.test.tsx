/**
 * A scroll of React Flow's own element becomes the same pan, and the element is
 * back at 0,0.
 *
 * `.react-flow` hides its overflow and React Flow draws a pan as its viewport's
 * transform, but the browser still scrolls the element to show what Tab
 * reaches past the canvas's edge. React Flow 11 never scrolls it back, so the
 * dot grid, the pane and the zoom buttons stayed that far off the window, and
 * every fit drew the nodes that far off where it put them
 * (`test_canvas_wrapper_scroll_e2e.py` does it with Tab). Both canvases pass
 * the handler to their React Flow (`reactFlowScroll.test.ts`).
 *
 * Drawn with React Flow itself, the handler on its `onScroll` as the canvases
 * pass it.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { ReactFlow, ReactFlowProvider, useStoreApi, type Node, type NodeProps } from "reactflow";
import { useFlowScrollAsPan } from "../../hook/useFlowScrollAsPan";

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

/** A node with a box of its own that scrolls, as an editor or a table does. */
function Card({ id }: NodeProps) {
  return (
    <div className="nowheel nodrag" data-testid={`rows-${id}`} style={{ height: 40, overflow: "auto" }}>
      rows
    </div>
  );
}

const NODE_TYPES = { card: Card };
const NODES: Node[] = [{ id: "far", type: "card", position: { x: 2400, y: 0 }, data: {} }];
const VIEW = { x: 120, y: 80, zoom: 0.75 };

type Seen = {
  store?: ReturnType<typeof useStoreApi>;
  onScroll?: ReturnType<typeof useFlowScrollAsPan>;
};

function Canvas({ pans, seen }: { pans?: boolean; seen: Seen }) {
  const onScroll = useFlowScrollAsPan(pans);
  seen.store = useStoreApi();
  seen.onScroll = onScroll;
  return (
    <ReactFlow
      nodes={NODES}
      edges={[]}
      nodeTypes={NODE_TYPES}
      defaultViewport={VIEW}
      onScroll={onScroll}
      proOptions={{ hideAttribution: true }}
    />
  );
}

/** Draw the canvas: its element, its view, and the handler it was given. */
function drawCanvas(pans?: boolean) {
  const seen: Seen = {};
  const { container } = render(
    <ReactFlowProvider>
      <div style={{ width: 800, height: 600 }}>
        <Canvas pans={pans} seen={seen} />
      </div>
    </ReactFlowProvider>,
  );
  const element = container.querySelector(".react-flow") as HTMLDivElement;
  return {
    element,
    seen,
    view: () => seen.store!.getState().transform,
    scrolled: () => [element.scrollLeft, element.scrollTop],
  };
}

/** Scroll *element* as the browser does to show something in it, and fire its scroll. */
function scrollBy(element: HTMLElement, across: number, down: number) {
  element.scrollLeft = across;
  element.scrollTop = down;
  fireEvent.scroll(element);
}

test("the canvas opens in its view, its element at 0,0", () => {
  const canvas = drawCanvas();
  expect({ scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
    scrolled: [0, 0],
    view: [VIEW.x, VIEW.y, VIEW.zoom],
  });
});

test("a scroll of React Flow's element is the same pan, and the element is back at 0,0", () => {
  const canvas = drawCanvas();
  scrollBy(canvas.element, 370, 40);
  expect({ scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
    scrolled: [0, 0],
    view: [VIEW.x - 370, VIEW.y - 40, VIEW.zoom],
  });
});

test("the scroll that putting the element back fires moves nothing", () => {
  const canvas = drawCanvas();
  scrollBy(canvas.element, 370, 40);
  fireEvent.scroll(canvas.element);
  expect({ scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
    scrolled: [0, 0],
    view: [VIEW.x - 370, VIEW.y - 40, VIEW.zoom],
  });
});

test("where the view is held (the notebook view's), the element is only put back", () => {
  const canvas = drawCanvas(false);
  scrollBy(canvas.element, 370, 40);
  expect({ scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
    scrolled: [0, 0],
    view: [VIEW.x, VIEW.y, VIEW.zoom],
  });
});

test("a scroll inside a node is the node's own", () => {
  const canvas = drawCanvas();
  const rows = screen.getByTestId("rows-far");
  scrollBy(rows, 0, 25);
  // Even one handed to the canvas's handler while React Flow's element is scrolled.
  canvas.element.scrollLeft = 30;
  act(() => {
    canvas.seen.onScroll!({ target: rows, currentTarget: canvas.element } as any);
  });
  expect({ rows: rows.scrollTop, scrolled: canvas.scrolled(), view: canvas.view() }).toEqual({
    rows: 25,
    scrolled: [30, 0],
    view: [VIEW.x, VIEW.y, VIEW.zoom],
  });
});
