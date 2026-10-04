/**
 * A node's widgets and their values survive a save (#662). Before, Trill had
 * no widget field: a reload reset every widget to its marker's default.
 */
import { TrillGenerator } from "../TrillGenerator";
import { nodeRunKey, normalizeWidgets } from "../utils/widgets/widgetModel";

const node = (data: Record<string, unknown>) => ({
  type: "curio.builtin/computation-analysis",
  position: { x: 0, y: 0 },
  data: { nodeId: "n1", code: "return [!! factor !!]", ...data },
});

describe("metadata.widgets", () => {
  beforeEach(() => TrillGenerator.reset());

  test("a node's widgets are written with their set values", () => {
    const widgets = [
      { name: "factor", type: "number", label: "Factor", default: 1, value: 2 },
      { name: "season", type: "choice", default: "summer", options: { choices: ["summer", "winter"] } },
    ];
    const spec = TrillGenerator.generateTrill([node({ widgets })], [], "W");
    expect(spec.dataflow.nodes[0].metadata.widgets).toEqual(widgets);
  });

  test("a node without widgets writes no widgets key", () => {
    const spec = TrillGenerator.generateTrill([node({}), node({ nodeId: "n2", widgets: [] })], [], "W");
    for (const written of spec.dataflow.nodes) {
      expect(written.metadata?.widgets).toBeUndefined();
    }
  });

  test("what is written reads back as the same widgets", () => {
    const widgets = [{ name: "factor", type: "number", default: 1, value: 2 }];
    const spec = TrillGenerator.generateTrill([node({ widgets })], [], "W");
    const back = normalizeWidgets(spec.dataflow.nodes[0].metadata.widgets);
    expect(back).toEqual(widgets);
    expect(nodeRunKey("c", back)).toBe(nodeRunKey("c", widgets));
  });
});
