/**
 * Duplicate selection (#662) on the saved shape of a dataflow. The copy gets
 * fresh ids and the edges between its nodes; an edge entering the selection
 * from outside is wired into the copy too, so both read the same context; an
 * edge leaving it is not copied. Each copy names its original at
 * `metadata.copiedFrom`, after the original's own lineage.
 */
import {
  duplicateSelection,
  lineageOf,
  type SpecEdge,
  type SpecNode,
} from "../../utils/scenarios/duplicateSelection";

const spec: { nodes: SpecNode[]; edges: SpecEdge[] } = {
  nodes: [
    { id: "load", type: "curio.builtin/data-loading", x: 0, y: 0, content: "load()" },
    { id: "pool", type: "curio.builtin/data-pool", x: 300, y: 0 },
    {
      id: "a",
      type: "curio.builtin/computation-analysis",
      x: 600,
      y: 0,
      content: "return arg * [!! factor !!]",
      metadata: { widgets: [{ name: "factor", type: "number", default: 1, value: 2 }], copiedFrom: ["root"] },
    },
    { id: "map", type: "curio.builtin/autk-grammar", x: 900, y: 0, content: "{}", dashboardPinned: true, dashboardX: 1, dashboardY: 2 },
    { id: "chart", type: "curio.builtin/vis-vega", x: 1200, y: 0 },
  ],
  edges: [
    { id: "e1", source: "load", target: "pool", sourceHandle: "out", targetHandle: "in" },
    { id: "e2", source: "pool", target: "a", sourceHandle: "out", targetHandle: "in_1" },
    { id: "e3", source: "a", target: "map", sourceHandle: "out" },
    { id: "e4", source: "map", target: "chart", sourceHandle: "out", targetHandle: "in" },
    { id: "e5", source: "chart", target: "map", type: "Interaction", sourceHandle: "in/out", targetHandle: "in/out" },
  ],
};

function duplicate(selected: string[]) {
  let n = 0;
  return duplicateSelection(spec, selected, { newId: () => `copy-${++n}`, offset: { x: 0, y: 400 } });
}

describe("duplicateSelection", () => {
  test("copies the selected nodes with fresh ids, below them", () => {
    const copy = duplicate(["a", "map"]);
    expect([...copy.ids]).toEqual([
      ["a", "copy-1"],
      ["map", "copy-2"],
    ]);
    expect(copy.nodes.map((n) => [n.id, n.x, n.y])).toEqual([
      ["copy-1", 600, 400],
      ["copy-2", 900, 400],
    ]);
    // Everything else is the original's: code, type, widgets and their values.
    expect(copy.nodes[0].content).toBe("return arg * [!! factor !!]");
    expect(copy.nodes[0].type).toBe("curio.builtin/computation-analysis");
    expect(copy.nodes[0].metadata!.widgets).toEqual(spec.nodes[2].metadata!.widgets);
    expect(copy.nodes[0].metadata!.widgets).not.toBe(spec.nodes[2].metadata!.widgets);
  });

  test("each copy names its original after the original's own lineage", () => {
    const copy = duplicate(["a", "map"]);
    expect(lineageOf(copy.nodes[0])).toEqual(["root", "a"]);
    expect(lineageOf(copy.nodes[1])).toEqual(["map"]);
    // The originals are untouched.
    expect(spec.nodes[2].metadata!.copiedFrom).toEqual(["root"]);
  });

  test("a copy is not a dashboard tile until someone pins it", () => {
    const map = duplicate(["map"]).nodes[0];
    expect(map.dashboardPinned).toBeUndefined();
    expect(map.dashboardX).toBeUndefined();
  });

  test("the edge between copied nodes is copied, and the edge entering the selection feeds the copy too", () => {
    const copy = duplicate(["a", "map"]);
    const wiring = copy.edges.map((e) => [e.source, e.target, e.targetHandle]);
    expect(wiring).toEqual([
      // The context edge keeps its circle.
      ["pool", "copy-1", "in_1"],
      // A missing handle is written out, so a load never reads it off the id.
      ["copy-1", "copy-2", "in"],
    ]);
    expect(copy.edges.every((e) => !/in_\d+$/.test(e.id))).toBe(true);
  });

  test("an edge leaving the selection is not copied: what reads the original keeps reading it", () => {
    const copy = duplicate(["a", "map"]);
    expect(copy.edges.some((e) => e.target === "chart")).toBe(false);
  });

  test("an interaction link from outside is not copied; one between copied views is", () => {
    expect(duplicate(["map"]).edges.some((e) => e.type === "Interaction")).toBe(false);
    const both = duplicate(["map", "chart"]);
    const link = both.edges.find((e) => e.type === "Interaction")!;
    expect([link.source, link.target, link.targetHandle]).toEqual(["copy-2", "copy-1", "in/out"]);
  });
});
