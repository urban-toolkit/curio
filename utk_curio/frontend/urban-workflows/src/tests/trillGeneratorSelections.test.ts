/**
 * A node's selection tags (#662) are saved at `metadata.selections` with the
 * ids each holds, so a run on the server and the headless runner read the
 * selection the canvas showed. Written only when the node has tags, so every
 * other node saves as it did before.
 */
import { TrillGenerator } from "../TrillGenerator";
import { normalizeSelections } from "../utils/references/selectionTags";

const node = (id: string, data: Record<string, unknown> = {}) => ({
  id,
  type: "curio.builtin/computation-analysis",
  position: { x: 0, y: 0 },
  data: { nodeId: id, code: "return [!! selection picked !!]", ...data },
});

describe("metadata.selections", () => {
  beforeEach(() => TrillGenerator.reset());

  test("a node's tags are written with their ids, or their count over the cap", () => {
    const selections = [
      { name: "picked", node: "chart", column: "osm_id", ids: [101, 104] },
      { name: "many", node: "map", column: "building_id", count: 20000 },
    ];
    const spec = TrillGenerator.generateTrill([node("a", { selections })], [], "W");
    expect(spec.dataflow.nodes[0].metadata.selections).toEqual(selections);
  });

  test("a node without tags writes no key", () => {
    const spec = TrillGenerator.generateTrill(
      [node("a"), node("b", { selections: undefined }), node("c", { selections: [] })],
      [],
      "W",
    );
    for (const written of spec.dataflow.nodes) {
      expect(written.metadata?.selections).toBeUndefined();
    }
  });

  test("what is written reads back as the same tags", () => {
    const selections = [{ name: "picked", node: "chart", column: "osm_id", ids: ["w1", 2] }];
    const spec = TrillGenerator.generateTrill([node("a", { selections })], [], "W");
    expect(normalizeSelections(spec.dataflow.nodes[0].metadata.selections)).toEqual(selections);
  });
});
