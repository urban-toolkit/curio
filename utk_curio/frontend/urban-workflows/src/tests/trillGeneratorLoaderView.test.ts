/**
 * A loader's view and its preview height are saved at `metadata.loaderView`
 * and `metadata.loaderPreviewHeight` (plans/data-loading-expressive-preview-memo.md),
 * only when set: a loader without them follows its code, so an example or an
 * older dataflow saves as it did before.
 */
import { TrillGenerator } from "../TrillGenerator";

const node = (id: string, data: Record<string, unknown> = {}) => ({
  id,
  type: "curio.builtin/data-loading",
  position: { x: 0, y: 0 },
  data: { nodeId: id, code: 'df = curio_load_data("data.x.y")\nreturn df', ...data },
});

describe("metadata.loaderView", () => {
  beforeEach(() => TrillGenerator.reset());

  test("a chosen view and a resized preview are written", () => {
    const spec = TrillGenerator.generateTrill(
      [node("a", { loaderView: "code" }), node("b", { loaderView: "preview", loaderPreviewHeight: 210 })],
      [],
      "W",
    );
    expect(spec.dataflow.nodes[0].metadata.loaderView).toBe("code");
    expect(spec.dataflow.nodes[1].metadata).toMatchObject({ loaderView: "preview", loaderPreviewHeight: 210 });
  });

  test("a loader with no view of its own writes no key, and nor does a value Curio does not know", () => {
    const spec = TrillGenerator.generateTrill([node("a"), node("b", { loaderView: "split" })], [], "W");
    for (const written of spec.dataflow.nodes) {
      expect(written.metadata?.loaderView).toBeUndefined();
      expect(written.metadata?.loaderPreviewHeight).toBeUndefined();
    }
  });
});
