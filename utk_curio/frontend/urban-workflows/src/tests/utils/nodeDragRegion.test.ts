/**
 * A double-click zooms the canvas onto a node only where a press would drag the
 * node: React Flow's own rule, nothing between the target and the node marked
 * `nodrag`. Editors, outputs, charts, maps and the connection dots keep their
 * own double-click (a word selected, a selection taken back, a map zoomed).
 *
 * A read-only canvas zooms the same way, on the same region: its nodes do not
 * drag, so React Flow leaves them without the `nopan` class it gives a node
 * that drags, and `keepPaneOffNodes` gives it to them.
 */
import { isNodeDragRegion, keepPaneOffNodes } from "../../utils/nodeDragRegion";

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

  test("finds the same region on a node that cannot drag, which React Flow draws without nopan", () => {
    const card =
      '<div class="resizable"><div class="curio-node-header"><span class="title">Title</span></div>' +
      '<div class="nowheel nodrag"><span class="code">x</span></div>' +
      '<div class="nodrag nopan nowheel"><canvas class="map"></canvas></div>' +
      '<div class="react-flow__handle nodrag nopan dot"></div></div>';
    // As React Flow draws a node that drags (on an editable canvas) and one
    // that does not (on a read-only canvas).
    const drags = node(card);
    drags.classList.add("nopan");
    const still = node(card);
    const region = (el: HTMLElement) =>
      [".title", ".resizable", ".code", ".map", ".dot"].map((s) => isNodeDragRegion(el.querySelector(s), el));
    expect(region(still)).toEqual([true, true, false, false, false]);
    expect(region(drags)).toEqual(region(still));
  });
});

describe("keepPaneOffNodes", () => {
  const at = { x: 0, y: 0 };

  test("gives each node React Flow's nopan class and keeps what the node has", () => {
    const data = { label: "Data Loading" };
    const marked = keepPaneOffNodes([
      { id: "a", position: at, data },
      { id: "b", position: at, data: {}, className: "curio-scenario-member" },
    ]);
    expect(marked.map((n) => n.className)).toEqual(["nopan", "curio-scenario-member nopan"]);
    expect(marked.map((n) => n.id)).toEqual(["a", "b"]);
    expect(marked[0].data).toBe(data);
  });

  test("leaves a node that has the class as it is, and changes none of the nodes it is given", () => {
    const has = { id: "a", position: at, data: {}, className: "curio-scenario-member nopan" };
    const plain = { id: "b", position: at, data: {} };
    const marked = keepPaneOffNodes([has, plain]);
    expect(marked[0]).toBe(has);
    expect(plain).toEqual({ id: "b", position: at, data: {} });
    expect(keepPaneOffNodes(marked)).toEqual(marked);
  });
});
