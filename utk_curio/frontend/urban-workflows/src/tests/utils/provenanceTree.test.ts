/**
 * The provenance history's layout, after Curio's Nest's list: its lines and
 * the branches folded under the item they left from.
 */
import { type HistoryEntry, type HistoryLine, historyLines, lineHolds, lineSize } from "../../utils/provenanceTree";

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
