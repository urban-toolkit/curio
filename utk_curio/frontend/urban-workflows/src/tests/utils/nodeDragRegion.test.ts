/**
 * A double-click zooms the canvas onto a node only where a press would drag the
 * node: React Flow's own rule, nothing between the target and the node marked
 * `nodrag`. Editors, outputs, charts, maps and the connection dots keep their
 * own double-click (a word selected, a selection taken back, a map zoomed).
 */
import { isNodeDragRegion } from "../../utils/nodeDragRegion";

function node(html: string): HTMLElement {
  const el = document.createElement("div");
  el.className = "react-flow__node";
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("isNodeDragRegion", () => {
  test("is true on the node's header and its card, where a press drags the node", () => {
    const el = node('<div class="resizable"><div class="curio-node-header"><span id="title">Title</span></div></div>');
    expect(isNodeDragRegion(el.querySelector("#title"), el)).toBe(true);
    expect(isNodeDragRegion(el.querySelector(".resizable"), el)).toBe(true);
    expect(isNodeDragRegion(el, el)).toBe(true);
  });

  test("is false inside anything marked nodrag: an editor, an output, a chart or a map", () => {
    const el = node(
      '<div class="resizable"><div class="nowheel nodrag"><div class="view-lines"><span id="code">x</span></div></div>' +
        '<div class="nodrag nopan nowheel"><canvas id="map"></canvas></div></div>',
    );
    expect(isNodeDragRegion(el.querySelector("#code"), el)).toBe(false);
    expect(isNodeDragRegion(el.querySelector("#map"), el)).toBe(false);
  });

  test("is false on a connection dot, which React Flow marks nodrag", () => {
    const el = node('<div class="react-flow__handle nodrag nopan" id="dot"></div>');
    expect(isNodeDragRegion(el.querySelector("#dot"), el)).toBe(false);
  });

  test("looks no further up than the node, and is false off the node", () => {
    const outer = document.createElement("div");
    outer.className = "nodrag";
    document.body.appendChild(outer);
    const el = document.createElement("div");
    el.className = "react-flow__node";
    el.innerHTML = '<span id="title">Title</span>';
    outer.appendChild(el);
    expect(isNodeDragRegion(el.querySelector("#title"), el)).toBe(true);
    expect(isNodeDragRegion(outer, el)).toBe(false);
    expect(isNodeDragRegion(null, el)).toBe(false);
  });
});
