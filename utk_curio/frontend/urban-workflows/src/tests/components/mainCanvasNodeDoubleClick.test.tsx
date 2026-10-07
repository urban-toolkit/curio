/**
 * A double-click on a node reaches the canvas's `onNodeDoubleClick` on a
 * read-only canvas as on an editable one, so MainCanvas's handler zooms onto the
 * node where a press would drag it (`isNodeDragRegion`) on both.
 *
 * React Flow's pane zooms the view 2x at the pointer on a double-click and stops
 * the event there, unless the target is inside an element with the `nopan`
 * class. React Flow gives that class to a node that drags; a read-only canvas's
 * nodes do not drag, so MainCanvas gives it to them with `keepPaneOffNodes`.
 *
 * Drawn with React Flow itself, set up as MainCanvas sets up each canvas: the
 * handler reads the event React Flow hands it, and a double-click the pane took
 * is a cancelled one (d3-zoom prevents its default) that the handler never sees.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReactFlow, ReactFlowProvider, type Node, type NodeProps } from "reactflow";
import { isNodeDragRegion, keepPaneOffNodes } from "../../utils/nodeDragRegion";

// jsdom polyfills React Flow needs (as in agentCanvasBridge.integration).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

/** A node card: its header, where a press drags the node, and an editor. */
function Card({ id }: NodeProps) {
  return (
    <div className="curio-node-card">
      <div className="curio-node-header" data-testid={`header-${id}`}>Data Loading</div>
      <div className="nowheel nodrag" data-testid={`editor-${id}`}>return df</div>
    </div>
  );
}

const NODE_TYPES = { card: Card };
const NODES: Node[] = [{ id: "producer", type: "card", position: { x: 0, y: 0 }, data: {} }];

type Seen = { node: string; dragRegion: boolean };

/** Draw `nodes` on a canvas whose nodes drag or not, and return what its
 *  `onNodeDoubleClick` hears: the node and whether the target is its drag region. */
function drawCanvas(nodes: Node[], nodesDraggable: boolean): Seen[] {
  const seen: Seen[] = [];
  render(
    <ReactFlowProvider>
      <div style={{ width: 800, height: 600 }}>
        <ReactFlow
          nodes={nodes}
          edges={[]}
          nodeTypes={NODE_TYPES}
          nodesDraggable={nodesDraggable}
          onNodeDoubleClick={(event, node) => {
            seen.push({ node: node.id, dragRegion: isNodeDragRegion(event.target, event.currentTarget) });
          }}
          proOptions={{ hideAttribution: true }}
        />
      </div>
    </ReactFlowProvider>,
  );
  return seen;
}

describe.each([
  // MainCanvas: `nodesDraggable={!isSharedView}`, and the shared view's nodes
  // go through keepPaneOffNodes.
  ["an editable canvas", true, () => NODES],
  ["a read-only canvas", false, () => keepPaneOffNodes(NODES)],
] as const)("on %s", (_canvas, nodesDraggable, drawn) => {
  test("a double-click on a node's header reaches the handler, in the node's drag region", () => {
    const seen = drawCanvas(drawn(), nodesDraggable);
    const notCancelled = fireEvent.doubleClick(screen.getByTestId("header-producer"));
    expect({ notCancelled, seen }).toEqual({
      notCancelled: true,
      seen: [{ node: "producer", dragRegion: true }],
    });
  });

  test("a double-click inside the node's editor reaches it outside the drag region, and the view stays", () => {
    const seen = drawCanvas(drawn(), nodesDraggable);
    const notCancelled = fireEvent.doubleClick(screen.getByTestId("editor-producer"));
    expect({ notCancelled, seen }).toEqual({
      notCancelled: true,
      seen: [{ node: "producer", dragRegion: false }],
    });
  });
});

test("without the class, a read-only canvas's pane takes the double-click and the handler never hears it", () => {
  // Why the read-only canvas marks its nodes: React Flow's pane zooms the view
  // 2x at the pointer, and the double-click ends there.
  const seen = drawCanvas(NODES, false);
  const notCancelled = fireEvent.doubleClick(screen.getByTestId("header-producer"));
  expect({ notCancelled, seen }).toEqual({ notCancelled: false, seen: [] });
});
