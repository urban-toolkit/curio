/**
 * A node that reads a file another saves (curio_computed_path) runs after it in
 * Run All, though no edge joins them, and playing the reader runs the saver
 * first. The ordering edge is not an input: run_plan.saved_file_edges is its
 * server twin.
 */
import type { Edge, Node } from "reactflow";
import { computeTopologicalLevels, nodesToRunUpTo, savedFileEdges } from "../../providers/flow/runLevels";

const node = (id: string, code: string): Node =>
  ({ id, position: { x: 0, y: 0 }, data: { nodeId: id, code } }) as unknown as Node;

const NODES = [
  node("reader", 'return pd.read_csv(curio_computed_path("summary"))'),
  node("saver", 'df.to_csv(curio_save_file("summary.csv"))\nreturn df'),
  node("folder", 'tiles = curio_save_folder("tiles")'),
  node("tiles-reader", "mosaic(curio_computed_path('tiles'))"),
  node("alone", "return 1"),
];

describe("saved-file ordering", () => {
  test("an edge from each saver of a name to each node reading it", () => {
    expect(savedFileEdges(NODES).map(e => [e.source, e.target, e.type])).toEqual([
      ["saver", "reader", "SavedFile"],
      ["folder", "tiles-reader", "SavedFile"],
    ]);
  });

  test("Run All puts the reader in a later level than the saver", () => {
    const levels = computeTopologicalLevels(NODES, []);
    const level = (id: string) => levels.findIndex(l => l.includes(id));
    expect(level("saver")).toBeLessThan(level("reader"));
    expect(level("folder")).toBeLessThan(level("tiles-reader"));
    expect(level("alone")).toBeGreaterThanOrEqual(0);
  });

  test("an edge already there is not counted twice", () => {
    const edges = savedFileEdges(NODES) as Edge[];
    expect(computeTopologicalLevels(NODES, edges)).toEqual(computeTopologicalLevels(NODES, []));
  });

  test("playing the reader runs the saver", () => {
    const { ancestorIds, willRun } = nodesToRunUpTo("reader", NODES, [], new Map());
    expect([...ancestorIds].sort()).toEqual(["reader", "saver"]);
    expect(willRun.has("saver")).toBe(true);
  });

  test("a name written by a widget orders nothing", () => {
    expect(savedFileEdges([node("a", "curio_save_folder([!! tiles !!])"), node("b", "curio_computed_path([!! tiles !!])")])).toEqual([]);
  });
});
