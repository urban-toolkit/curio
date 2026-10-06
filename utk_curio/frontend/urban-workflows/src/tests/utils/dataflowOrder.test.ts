/**
 * The order a dataflow reads in as a list (utils/dataflowOrder): the notebook
 * view lays its cells out in it and Export as notebook writes its cells in it,
 * so the two always agree.
 */
import { dataflowOrder } from "../../utils/dataflowOrder";
import { directedEdgesOf } from "../../providers/flow/runLevels";
import { trillToNotebook } from "../../NotebookConvertor";

type TestEdge = { source: string; target: string; sourceHandle?: string; targetHandle?: string };

const ids = (list: { id: string }[]) => list.map((n) => n.id);
const nodes = (...names: string[]) => names.map((id) => ({ id }));
const edge = (
  source: string,
  target: string,
  handles: { sourceHandle?: string; targetHandle?: string } = {},
): TestEdge => ({ source, target, ...handles });

describe("dataflowOrder", () => {
  test("every node comes after the nodes it reads from", () => {
    // Given out of order on purpose: chart, then its source, then the middle.
    const order = dataflowOrder(nodes("chart", "load", "clean"), [
      edge("load", "clean"),
      edge("clean", "chart"),
    ]);
    expect(ids(order)).toEqual(["load", "clean", "chart"]);
  });

  test("each node is followed by the chain it feeds before the next unrelated node", () => {
    const order = dataflowOrder(nodes("load", "extra", "clean", "chart"), [
      edge("load", "clean"),
      edge("clean", "chart"),
    ]);
    expect(ids(order)).toEqual(["load", "clean", "chart", "extra"]);
  });

  test("of the nodes one feeds, the newest connection comes first, right below it", () => {
    // `added` was wired from `load` last, as a cell added under it is.
    const order = dataflowOrder(nodes("load", "clean", "chart", "added"), [
      edge("load", "clean"),
      edge("clean", "chart"),
      edge("load", "added"),
    ]);
    expect(ids(order)).toEqual(["load", "added", "clean", "chart"]);
  });

  test("a node fed by two others waits for both, then follows the second", () => {
    const order = dataflowOrder(nodes("a", "b", "join", "after"), [
      edge("a", "join"),
      edge("b", "join"),
    ]);
    expect(ids(order)).toEqual(["a", "b", "join", "after"]);
  });

  test("a node fed by two others comes after both", () => {
    const order = dataflowOrder(nodes("join", "a", "b"), [edge("a", "join"), edge("b", "join")]);
    expect(ids(order).indexOf("join")).toBe(2);
  });

  test("nodes nothing orders keep the order they are given", () => {
    expect(ids(dataflowOrder(nodes("x", "y", "z"), []))).toEqual(["x", "y", "z"]);
  });

  test("an interaction link orders nothing", () => {
    // The chart and the pool select for each other both ways; only the data
    // edge from the pool decides the order.
    const edges = [
      edge("pool", "chart", { sourceHandle: "out", targetHandle: "in" }),
      edge("chart", "pool", { sourceHandle: "in/out", targetHandle: "in/out" }),
    ];
    expect(ids(dataflowOrder(nodes("chart", "pool"), directedEdgesOf(edges)))).toEqual(["pool", "chart"]);
  });

  test("nodes caught in a cycle go last instead of vanishing", () => {
    const order = dataflowOrder(nodes("a", "b", "c"), [edge("a", "b"), edge("b", "a")]);
    expect(ids(order)).toEqual(["c", "a", "b"]);
  });

  test("Export as notebook writes its cells in the same order", () => {
    const spec = {
      dataflow: {
        nodes: [
          { id: "chart", type: "curio.builtin/computation-analysis", x: 0, y: 0, content: "return arg" },
          { id: "load", type: "curio.builtin/computation-analysis", x: 0, y: 0, content: "return 1" },
          { id: "pool", type: "curio.builtin/computation-analysis", x: 0, y: 0, content: "return arg" },
        ],
        edges: [
          { id: "e1", source: "load", target: "pool" },
          { id: "e2", source: "pool", target: "chart" },
          { id: "e3", source: "chart", target: "pool", type: "Interaction" },
        ],
        name: "order",
        task: "",
        timestamp: 0,
        provenance_id: "p",
      },
    };
    const exported = trillToNotebook(spec as any).cells
      .filter((cell) => cell.cell_type === "markdown")
      .map((cell) => ["chart", "load", "pool"].find((id) => cell.source.includes(`\`${id}\``)));
    const view = dataflowOrder(spec.dataflow.nodes, spec.dataflow.edges.filter((e) => e.type !== "Interaction"));
    expect(exported).toEqual(ids(view));
    expect(exported).toEqual(["load", "pool", "chart"]);
  });
});
