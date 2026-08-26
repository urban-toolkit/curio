import { pickNodeAtPoint, hasAgentDrag, AGENT_DRAG_MIME, type NodeRect } from "../../utils/agentCatalogEvents";

/**
 * `hasAgentDrag` decides whether `dragover` should set `dropEffect="copy"`. It
 * must read `dataTransfer.types` (not `getData`, which returns "" mid-drag), or
 * the browser cancels the agent drop (effectAllowed="copy" vs a "move" effect).
 */
describe("hasAgentDrag", () => {
  const dt = (types: string[]): DataTransfer => ({ types } as unknown as DataTransfer);

  it("is true when the agent MIME is among the drag types", () => {
    expect(hasAgentDrag(dt([AGENT_DRAG_MIME]))).toBe(true);
    expect(hasAgentDrag(dt(["text/plain", AGENT_DRAG_MIME]))).toBe(true);
  });

  it("is false for non-agent drags and null", () => {
    expect(hasAgentDrag(dt(["application/reactflow"]))).toBe(false);
    expect(hasAgentDrag(dt([]))).toBe(false);
    expect(hasAgentDrag(null)).toBe(false);
  });
});

/**
 * `pickNodeAtPoint` decides whether an agent dropped from the palette attaches
 * to a node (by hit-testing the drop point against node geometry, in flow
 * coordinates) or to the canvas. Coordinate hit-testing avoids the DOM-layer
 * quirk where React Flow's pane is the drop-event target rather than the node.
 */
describe("pickNodeAtPoint", () => {
  const nodes: NodeRect[] = [
    { id: "n1", position: { x: 0, y: 0 }, width: 100, height: 50 },
    { id: "n2", position: { x: 200, y: 200 }, width: 80, height: 40 },
  ];

  it("returns the id of the node whose box contains the point", () => {
    expect(pickNodeAtPoint(nodes, { x: 50, y: 25 })).toBe("n1");
    expect(pickNodeAtPoint(nodes, { x: 210, y: 210 })).toBe("n2");
  });

  it("matches on the node's edges (inclusive)", () => {
    expect(pickNodeAtPoint(nodes, { x: 0, y: 0 })).toBe("n1");
    expect(pickNodeAtPoint(nodes, { x: 100, y: 50 })).toBe("n1");
  });

  it("returns null over empty canvas", () => {
    expect(pickNodeAtPoint(nodes, { x: 150, y: 150 })).toBeNull();
    expect(pickNodeAtPoint([], { x: 0, y: 0 })).toBeNull();
  });

  it("prefers the topmost (last-rendered) node when boxes overlap", () => {
    const overlapping: NodeRect[] = [
      { id: "under", position: { x: 0, y: 0 }, width: 100, height: 100 },
      { id: "over", position: { x: 50, y: 50 }, width: 100, height: 100 },
    ];
    expect(pickNodeAtPoint(overlapping, { x: 60, y: 60 })).toBe("over");
  });

  it("prefers positionAbsolute and tolerates missing geometry", () => {
    const n: NodeRect[] = [
      { id: "abs", position: { x: 0, y: 0 }, positionAbsolute: { x: 500, y: 500 }, width: 40, height: 40 },
      { id: "nogeo", width: 40, height: 40 },
    ];
    expect(pickNodeAtPoint(n, { x: 510, y: 510 })).toBe("abs");
    expect(pickNodeAtPoint(n, { x: 5, y: 5 })).toBeNull(); // "abs" uses absolute; "nogeo" has no origin
  });
});
