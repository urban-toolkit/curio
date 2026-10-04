/**
 * A copy made by Duplicate selection names where it comes from (#662), at
 * `metadata.copiedFrom`, written only on a copy so every other node saves as
 * it did before.
 */
import { TrillGenerator } from "../TrillGenerator";
import { lineageFromSpec } from "../utils/scenarios/duplicateSelection";

const node = (id: string, data: Record<string, unknown> = {}) => ({
  id,
  type: "curio.builtin/computation-analysis",
  position: { x: 0, y: 0 },
  data: { nodeId: id, code: "return arg", ...data },
});

describe("metadata.copiedFrom", () => {
  beforeEach(() => TrillGenerator.reset());

  test("a copy's lineage is written, oldest first", () => {
    const spec = TrillGenerator.generateTrill([node("copy", { copiedFrom: ["root", "a"] })], [], "W");
    expect(spec.dataflow.nodes[0].metadata.copiedFrom).toEqual(["root", "a"]);
  });

  test("a node that is not a copy writes no key", () => {
    const spec = TrillGenerator.generateTrill(
      [node("a"), node("b", { copiedFrom: undefined }), node("c", { copiedFrom: [] })],
      [],
      "W",
    );
    for (const written of spec.dataflow.nodes) {
      expect(written.metadata?.copiedFrom).toBeUndefined();
    }
  });

  test("what is written reads back as the same lineage, and anything else is dropped", () => {
    const spec = TrillGenerator.generateTrill([node("copy", { copiedFrom: ["a"] })], [], "W");
    expect(lineageFromSpec(spec.dataflow.nodes[0].metadata.copiedFrom)).toEqual(["a"]);
    expect(lineageFromSpec(["a", "", 3, null])).toEqual(["a"]);
    expect(lineageFromSpec("a")).toEqual([]);
  });
});
