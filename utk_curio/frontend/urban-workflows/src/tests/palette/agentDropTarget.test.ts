import { resolveAgentDropTarget } from "../../utils/agentsPaletteEvents";

/**
 * `resolveAgentDropTarget` decides whether an agent dropped from the palette
 * attaches to a specific graph node or to the canvas, by walking up the drop's
 * DOM target to React Flow's `.react-flow__node[data-id]` wrapper.
 */
describe("resolveAgentDropTarget", () => {
  function buildNode(id: string): { wrapper: HTMLElement; inner: HTMLElement } {
    const wrapper = document.createElement("div");
    wrapper.className = "react-flow__node react-flow__node-DATA_POOL";
    wrapper.setAttribute("data-id", id);
    const inner = document.createElement("div");
    inner.className = "node-body";
    wrapper.appendChild(inner);
    return { wrapper, inner };
  }

  it("returns a node target when dropped on the node wrapper", () => {
    const { wrapper } = buildNode("n-42");
    expect(resolveAgentDropTarget(wrapper)).toEqual({ kind: "node", targetId: "n-42" });
  });

  it("returns a node target when dropped on a descendant of the node", () => {
    const { inner } = buildNode("n-7");
    // A drop lands on the innermost element under the cursor, not the wrapper.
    expect(resolveAgentDropTarget(inner)).toEqual({ kind: "node", targetId: "n-7" });
  });

  it("falls back to the canvas when dropped off any node", () => {
    const pane = document.createElement("div");
    pane.className = "react-flow__pane";
    expect(resolveAgentDropTarget(pane)).toEqual({ kind: "canvas" });
  });

  it("falls back to the canvas when the node wrapper has no id", () => {
    const wrapper = document.createElement("div");
    wrapper.className = "react-flow__node"; // no data-id
    expect(resolveAgentDropTarget(wrapper)).toEqual({ kind: "canvas" });
  });

  it("falls back to the canvas for a null target", () => {
    expect(resolveAgentDropTarget(null)).toEqual({ kind: "canvas" });
  });

  it("falls back to the canvas for a non-Element target (no closest)", () => {
    // e.g. a text node or a non-DOM EventTarget — must not throw.
    expect(resolveAgentDropTarget({} as EventTarget)).toEqual({ kind: "canvas" });
  });
});
