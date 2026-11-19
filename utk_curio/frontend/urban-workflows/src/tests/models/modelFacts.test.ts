import { modelInfoRows, modelNodeLabel } from "../../components/models/catalog/modelFacts";
import { ddrnetPackage, template } from "../_support/modelPackages";

/**
 * The details' Node row: the node a drop of the model's card makes on the
 * canvas. A model package of one node names it; one of several, such as SAM
 * 3's (Track Objects and Segment Images), names them as a choice, since the
 * drop makes the one picked from its menu, in the menu's order
 * (`packageCardNodes`). The package's own section counts the nodes under
 * Nodes, so the Model section's row stays Node.
 */

type ModelPackage = Parameters<typeof modelInfoRows>[0];

const TRACK = template({ id: "model.curio.sam3/track-objects@1", templateId: "track-objects", label: "Track Objects" });
const SEGMENT = template({
  id: "model.curio.sam3/segment-images@1", templateId: "segment-images", label: "Segment Images",
});

function rowOf(pkg: ModelPackage, label: string) {
  return modelInfoRows(pkg).find((row) => row.label === label);
}

describe("the node a model's card makes", () => {
  test("a model package of one node names it", () => {
    const pkg = ddrnetPackage() as ModelPackage;
    expect(rowOf(pkg, "Node")?.value).toBe("Image Segmentation");
  });

  test("a model package of two nodes names both as a choice, in its drop menu's order", () => {
    const pkg = ddrnetPackage({ templates: [TRACK, SEGMENT] }) as ModelPackage;
    expect(modelNodeLabel(pkg)).toBe("Track Objects or Segment Images");
    expect(rowOf(pkg, "Node")?.value).toBe("Track Objects or Segment Images");
    expect(modelInfoRows(pkg).filter((row) => row.label.startsWith("Node"))).toHaveLength(1);
    // The menu lists a node by its palette order first, then the manifest's.
    const reordered = ddrnetPackage({
      templates: [{ ...TRACK, paletteOrder: 2 }, { ...SEGMENT, paletteOrder: 1 }],
    }) as ModelPackage;
    expect(modelNodeLabel(reordered)).toBe("Segment Images or Track Objects");
  });

  test("three nodes read as a list ending in or", () => {
    const third = template({ id: "pkg/third@1", templateId: "third", label: "Third" });
    const pkg = ddrnetPackage({ templates: [TRACK, SEGMENT, third] }) as ModelPackage;
    expect(modelNodeLabel(pkg)).toBe("Track Objects, Segment Images or Third");
  });

  test("a model package with no node has no Node row", () => {
    const pkg = ddrnetPackage({ templates: [] }) as ModelPackage;
    expect(modelNodeLabel(pkg)).toBeNull();
    expect(rowOf(pkg, "Node")).toBeUndefined();
  });
});
