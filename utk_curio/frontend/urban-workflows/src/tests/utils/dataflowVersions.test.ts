/**
 * A dataflow's versions as its provenance history lists them: numbered in the
 * order they were recorded, each named by the change that made it.
 */
import { changedNodeKind, versionCounts, versionItems, versionTitle } from "../../utils/dataflowVersions";
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
