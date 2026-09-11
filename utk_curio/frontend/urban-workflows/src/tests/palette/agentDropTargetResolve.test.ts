/**
 * Node, then connection, then canvas - the precedence the drop and the
 * drag-over highlight share (#296).
 *
 * `pickEdge` is injected throughout so this file needs no DOM at all, the same
 * way its sibling `agentDropTarget.test.ts` needs none.
 */
import {
  resolveAgentDropTarget,
  type NodeRect,
} from "../../utils/agentCatalogEvents";

const NODES: NodeRect[] = [
  { id: "n1", position: { x: 0, y: 0 }, width: 100, height: 50 },
  { id: "n2", position: { x: 200, y: 200 }, width: 100, height: 50 },
];

describe("resolveAgentDropTarget", () => {
  it("resolves a node when the point is inside one", () => {
    const pickEdge = jest.fn(() => "edge-1");
    const target = resolveAgentDropTarget({
      nodes: NODES,
      flowPoint: { x: 50, y: 25 },
      clientX: 50,
      clientY: 25,
      pickEdge,
    });
    expect(target).toEqual({ kind: "node", targetId: "n1" });
  });

  it("never hit-tests an edge when a node was hit", () => {
    // An edge routed underneath a node must not light up, and the DOM
    // hit-test (which forces a layout read) must not run at all.
    const pickEdge = jest.fn(() => "edge-1");
    resolveAgentDropTarget({
      nodes: NODES,
      flowPoint: { x: 50, y: 25 },
      clientX: 50,
      clientY: 25,
      pickEdge,
    });
    expect(pickEdge).not.toHaveBeenCalled();
  });

  it("resolves a connection when no node contains the point", () => {
    const pickEdge = jest.fn(() => "edge-42");
    const target = resolveAgentDropTarget({
      nodes: NODES,
      flowPoint: { x: 500, y: 500 },
      clientX: 640,
      clientY: 480,
      pickEdge,
    });
    expect(target).toEqual({ kind: "connection", targetId: "edge-42" });
    expect(pickEdge).toHaveBeenCalledWith(640, 480);
  });

  it("falls back to the canvas when neither hits", () => {
    const target = resolveAgentDropTarget({
      nodes: NODES,
      flowPoint: { x: 500, y: 500 },
      clientX: 640,
      clientY: 480,
      pickEdge: () => null,
    });
    expect(target).toEqual({ kind: "canvas" });
  });

  it("the hover feed and the drop resolve through the same code path", () => {
    // The claim #296 asks to be recorded: main's DOM hit-test stays, and the
    // highlight does not get a second opinion about where an edge is. Both
    // callers pass through here, so a divergence is impossible by construction
    // - and the edge is consulted exactly once, and only when no node was hit.
    const pickEdge = jest.fn(() => "edge-7");
    const query = {
      nodes: NODES,
      flowPoint: { x: 500, y: 500 },
      clientX: 10,
      clientY: 20,
      pickEdge,
    };
    const onDragOver = resolveAgentDropTarget(query);
    const onDrop = resolveAgentDropTarget(query);
    expect(onDragOver).toEqual(onDrop);
    expect(pickEdge).toHaveBeenCalledTimes(2);
  });

  it("carries the node's own id, back-to-front, so the topmost wins", () => {
    const overlapping: NodeRect[] = [
      { id: "under", position: { x: 0, y: 0 }, width: 100, height: 100 },
      { id: "over", position: { x: 0, y: 0 }, width: 100, height: 100 },
    ];
    const target = resolveAgentDropTarget({
      nodes: overlapping,
      flowPoint: { x: 10, y: 10 },
      clientX: 0,
      clientY: 0,
      pickEdge: () => null,
    });
    expect(target).toEqual({ kind: "node", targetId: "over" });
  });
});
