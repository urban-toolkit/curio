/**
 * A dataflow's versions as its provenance history lists them: numbered in the
 * order they were recorded, each named by the change that made it.
 */
import {
  changedNodeKind,
  serverVersionItems,
  versionCounts,
  versionItems,
  versionTitle,
} from "../../utils/dataflowVersions";
import type { ServerVersion } from "../../api/historyApi";
import { historyLines } from "../../utils/provenanceTree";
import { clearCategoryDescriptors, registerCategoryDescriptor } from "../_support/categoryDescriptors";

const node = (id: string, type = "acme.charts/bar@1") => ({ id, type, x: 0, y: 0 });
const preview = (ids: string[], edges: [string, string][] = []) => ({
  nodes: ids.map((id) => node(id)),
  edges: edges.map(([source, target]) => ({ source, target })),
});

beforeAll(() => registerCategoryDescriptor("acme.charts/bar@1", "vis_grammar", "Bar chart"));
afterAll(() => clearCategoryDescriptors());

describe("versionItems", () => {
  const history = {
    nodes: [
      { id: "v1", timestamp: Date.UTC(2026, 9, 20, 14, 5), preview: preview([]) },
      { id: "v2", timestamp: Date.UTC(2026, 9, 20, 14, 6), preview: preview(["a"]) },
      { id: "v3", timestamp: Date.UTC(2026, 9, 20, 14, 7), preview: preview(["a", "b"]) },
      { id: "v4", preview: preview(["a", "b"], [["a", "b"]]) },
    ],
    edges: [
      { source: "v1", target: "v2", label: "Node added" },
      { source: "v2", target: "v3", label: "Node added" },
      { source: "v3", target: "v4", label: "Connection added" },
    ],
  };

  test("numbers the versions from 1 in the order they were recorded, each from the one it was made from", () => {
    const items = versionItems(history);
    expect(items.map((item) => [item.id, item.tag, item.order, item.parentId])).toEqual([
      ["v1", "1", 0, null],
      ["v2", "2", 1, "v1"],
      ["v3", "3", 2, "v2"],
      ["v4", "4", 3, "v3"],
    ]);
  });

  test("names each version by its change, with the kind of node it added", () => {
    expect(versionItems(history).map((item) => item.title)).toEqual([
      "Empty dataflow",
      "Node added: Bar chart",
      "Node added: Bar chart",
      "Connection added",
    ]);
  });

  test("gives the time on the row and the date and time on hover, or nothing when none was recorded", () => {
    const [first, , , last] = versionItems(history);
    expect(first.when).not.toBe("");
    expect(first.tooltip).toBe(new Date(Date.UTC(2026, 9, 20, 14, 5)).toLocaleString());
    expect(last.when).toBe("");
    expect(last.tooltip).toBeUndefined();
  });

  test("a change from a version the history does not hold makes no parent", () => {
    const items = versionItems({
      nodes: [{ id: "v1", preview: preview(["a"]) }],
      edges: [{ source: "gone", target: "v1", label: "Node added" }],
    });
    expect(items[0].parentId).toBeNull();
    expect(items[0].title).toBe("First version");
  });

  test("an empty or missing history has no item", () => {
    expect(versionItems(null)).toEqual([]);
    expect(versionItems({})).toEqual([]);
  });
});

describe("serverVersionItems", () => {
  const at = (minute: number) => Date.UTC(2026, 9, 28, 14, minute);
  const ana = { kind: "person", account: "1", name: "Ana" };
  // The server's points for a loaded dataflow of one node, then Ana's typing,
  // version 2 put back, and a File > Save.
  const versions: ServerVersion[] = [
    { id: "p1", parent: null, at: at(0), kind: "load", what: "", by: null, preview: preview([]) },
    { id: "p2", parent: "p1", at: at(0), kind: "load", what: "Node added", by: null, preview: preview(["a"]) },
    { id: "p3", parent: "p2", at: at(1), kind: "typing", what: "Ana edited", by: ana, preview: preview(["a"]) },
    { id: "p4", parent: "p2", at: at(2), kind: "putBack", what: "Put back", restores: "p2", by: ana, preview: preview(["a"]) },
    { id: "p5", parent: "p4", at: at(3), kind: "saved", what: "Saved", by: ana, preview: preview(["a"]) },
  ];

  test("numbers the versions from 1 in the order they were made, each from the one it was made from", () => {
    expect(serverVersionItems(versions).map((item) => [item.id, item.tag, item.order, item.parentId])).toEqual([
      ["p1", "1", 0, null],
      ["p2", "2", 1, "p1"],
      ["p3", "3", 2, "p2"],
      ["p4", "4", 3, "p2"],
      ["p5", "5", 4, "p4"],
    ]);
  });

  test("names a version by its change, a put-back by the version it put back, and the rest by what changed", () => {
    expect(serverVersionItems(versions).map((item) => item.title)).toEqual([
      "Empty dataflow",
      "Node added: Bar chart",
      "Ana edited",
      "Put back version 2",
      "Saved",
    ]);
  });

  test("a put-back starts the line to the newest version, and the versions after the one put back fold under it", () => {
    const [line] = historyLines(serverVersionItems(versions));
    expect(line.rows.map((row) => row.id)).toEqual(["p1", "p2", "p4", "p5"]);
    const p2 = line.rows[1];
    expect(p2.branches.map((branch) => branch.rows.map((row) => row.id))).toEqual([["p3"]]);
  });

  test("a put-back of a version the history no longer holds, and a first version left after a clear", () => {
    const items = serverVersionItems([
      { id: "p9", parent: null, at: at(5), kind: "typing", what: "Ana edited", by: ana, preview: preview(["a"]) },
      { id: "p10", parent: "p9", at: at(6), kind: "putBack", what: "Put back", restores: "p2", by: ana, preview: preview([]) },
    ]);
    expect(items.map((item) => [item.title, item.parentId])).toEqual([
      ["Ana edited", null],
      ["Put back", "p9"],
    ]);
  });
});

describe("versionTitle and changedNodeKind", () => {
  test("a removed node is named too", () => {
    expect(versionTitle("Node deleted", preview(["a", "b"]), preview(["a"]))).toBe("Node deleted: Bar chart");
  });

  test("no kind when no node changed, several did, or the kind is not registered", () => {
    expect(changedNodeKind(preview(["a"]), preview(["a"]))).toBeNull();
    expect(changedNodeKind(preview([]), preview(["a", "b"]))).toBeNull();
    expect(changedNodeKind({ nodes: [], edges: [] }, { nodes: [node("a", "acme.gone/x@1")], edges: [] })).toBeNull();
    expect(versionTitle("Node added", { nodes: [], edges: [] }, { nodes: [node("a", "acme.gone/x@1")], edges: [] })).toBe(
      "Node added",
    );
  });

  test("the first version is the empty dataflow, or the one it opened with", () => {
    expect(versionTitle(undefined, undefined, preview([]))).toBe("Empty dataflow");
    expect(versionTitle(undefined, undefined, null)).toBe("Empty dataflow");
    expect(versionTitle(undefined, undefined, preview(["a"]))).toBe("First version");
  });
});

describe("versionCounts", () => {
  test("counts nodes and connections, one or several", () => {
    expect(versionCounts(preview(["a"]))).toBe("1 node, 0 connections");
    expect(versionCounts(preview(["a", "b"], [["a", "b"]]))).toBe("2 nodes, 1 connection");
    expect(versionCounts(null)).toBe("0 nodes, 0 connections");
  });
});
