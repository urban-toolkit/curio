/**
 * The provenance history's layout, after Curio's Nest: the List's lines and
 * folded branches, the Graph's columns and rows, and the links between boxes.
 */
import {
  type HistoryEntry,
  type HistoryLine,
  historyGraph,
  historyLines,
  lineHolds,
  lineSize,
  linkEnds,
  linkPath,
} from "../../utils/provenanceTree";

/** Entries from "id<-parent" pairs, in the order they were made. */
const history = (...pairs: string[]): HistoryEntry[] =>
  pairs.map((pair, order) => {
    const [id, parentId] = pair.split("<-");
    return { id, parentId: parentId ?? null, order };
  });

/** A line as nested arrays: each row its id, then its branches. */
const shape = (line: HistoryLine): unknown[] =>
  line.rows.map((row) => (row.branches.length ? [row.id, row.branches.map(shape)] : row.id));

describe("the List's lines", () => {
  test("a chain is one line, oldest first", () => {
    const lines = historyLines(history("a", "b<-a", "c<-b", "d<-c"));
    expect(lines.map(shape)).toEqual([["a", "b", "c", "d"]]);
  });

  test("the main line runs to the newest item; an earlier try hangs where it left", () => {
    // Back to b after c and d, then e and f from b: f is the newest.
    const lines = historyLines(history("a", "b<-a", "c<-b", "d<-c", "e<-b", "f<-e"));
    expect(lines.map(shape)).toEqual([["a", ["b", [["c", "d"]]], "e", "f"]]);
  });

  test("an older branch stays the main line while it holds the newest item", () => {
    // e was tried from b, then work went on from d: g is the newest.
    const lines = historyLines(history("a", "b<-a", "c<-b", "d<-c", "e<-b", "g<-d"));
    expect(lines.map(shape)).toEqual([["a", ["b", [["e"]]], "c", "d", "g"]]);
  });

  test("several branches from one item, each to its own newest, oldest first", () => {
    const lines = historyLines(history("a", "b<-a", "c<-a", "d<-a", "e<-d"));
    expect(lines.map(shape)).toEqual([[["a", [["b"], ["c"]]], "d", "e"]]);
  });

  test("a branch of a branch nests under it", () => {
    const lines = historyLines(history("a", "b<-a", "c<-b", "x<-b", "y<-a", "z<-y"));
    // Main: a, y, z. From a: b then x, the newer, with c off b.
    expect(lines.map(shape)).toEqual([[["a", [[["b", [["c"]]], "x"]]], "y", "z"]]);
  });

  test("an item whose parent is missing starts a line of its own", () => {
    const lines = historyLines(history("a", "b<-a", "c<-gone", "d<-c"));
    expect(lines.map(shape)).toEqual([["a", "b"], ["c", "d"]]);
  });

  test("a loop in the parent links lists every item once", () => {
    const lines = historyLines([
      { id: "a", parentId: "c", order: 0 },
      { id: "b", parentId: "a", order: 1 },
      { id: "c", parentId: "b", order: 2 },
    ]);
    const ids = lines.flatMap((line) => line.rows.map((row) => row.id));
    expect(ids.sort()).toEqual(["a", "b", "c"]);
  });

  test("a chain thousands of items long is laid out without running out of stack", () => {
    const pairs = ["v0"];
    for (let i = 1; i < 20000; i += 1) pairs.push(`v${i}<-v${i - 1}`);
    const lines = historyLines(history(...pairs));
    expect(lines).toHaveLength(1);
    expect(lines[0].rows).toHaveLength(20000);
  });

  test("a line counts and finds the items on its branches", () => {
    const [line] = historyLines(history("a", "b<-a", "c<-b", "d<-c", "e<-b", "f<-e"));
    const branch = line.rows[1].branches[0];
    expect(lineSize(line)).toBe(6);
    expect(lineSize(branch)).toBe(2);
    expect(lineHolds(branch, "d")).toBe(true);
    expect(lineHolds(branch, "f")).toBe(false);
    expect(lineHolds(line, "d")).toBe(true);
    expect(lineHolds(line, null)).toBe(false);
  });
});

describe("the Graph's boxes", () => {
  const place = (...pairs: string[]) => {
    const graph = historyGraph(historyLines(history(...pairs)));
    return {
      graph,
      at: Object.fromEntries(graph.boxes.map((box) => [box.id, [box.col, box.row]])),
    };
  };

  test("a chain runs down one column, one link between each two items", () => {
    const { graph, at } = place("a", "b<-a", "c<-b");
    expect(at).toEqual({ a: [0, 0], b: [0, 1], c: [0, 2] });
    expect(graph.links).toEqual([
      { from: "a", to: "b", kind: "next" },
      { from: "b", to: "c", kind: "next" },
    ]);
    expect(graph.cols).toBe(1);
  });

  test("a branch starts beside its item in the next column, and the line moves down past it", () => {
    const { graph, at } = place("a", "b<-a", "c<-b", "d<-c", "e<-b", "f<-e");
    expect(at).toEqual({ a: [0, 0], b: [0, 1], c: [1, 1], d: [1, 2], e: [0, 3], f: [0, 4] });
    expect(graph.links).toContainEqual({ from: "b", to: "c", kind: "branch" });
    expect(graph.links).toContainEqual({ from: "b", to: "e", kind: "next" });
    expect(graph.cols).toBe(2);
    expect(graph.rows).toBe(5);
  });

  test("a second branch from one item starts below the first", () => {
    const { at } = place("a", "b<-a", "c<-a", "d<-a");
    expect(at).toEqual({ a: [0, 0], b: [1, 0], c: [1, 1], d: [0, 2] });
  });

  test("no two boxes share a cell, and every item but a line's first has one link in", () => {
    const { graph } = place("a", "b<-a", "c<-b", "x<-b", "y<-a", "z<-y", "w<-gone");
    const cells = graph.boxes.map((box) => `${box.col},${box.row}`);
    expect(new Set(cells).size).toBe(cells.length);
    const into = graph.links.map((link) => link.to).sort();
    expect(into).toEqual(["b", "c", "x", "y", "z"]);
  });
});

describe("the links' paths", () => {
  const box = (x: number, y: number, h = 34) => ({ x, y, w: 200, h });

  test("an item and the next one under it: straight down between their middles", () => {
    expect(linkPath("next", box(0, 0, 60), box(0, 100), 34)).toBe("M100 60V100");
    expect(linkEnds("next", box(0, 0, 60), box(0, 100), 34)).toEqual([100, 60, 100, 100]);
  });

  test("a branch beside its item: straight across their title lines", () => {
    expect(linkPath("branch", box(0, 0, 120), box(236, 0), 34)).toBe("M200 17H236");
  });

  test("a branch below its item: the Nest's rounded elbow", () => {
    const d = linkPath("branch", box(0, 0), box(236, 100), 34);
    expect(d).toBe("M200 17H210Q218 17 218 25V109Q218 117 226 117H236");
    expect(linkEnds("branch", box(0, 0), box(236, 100), 34)).toEqual([200, 17, 236, 117]);
  });
});
