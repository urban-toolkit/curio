import { modelInfoRows, modelNodeLabel } from "../../components/models/catalog/modelFacts";
import { ddrnetPackage, template } from "../_support/modelPackages";

/**
 * The details' row of the nodes a model's card makes on the canvas: a model
 * package of one node names it under Node; one of several, such as SAM 3's
 * (Track Objects and Segment Images), names each under Nodes, in the order
 * its card's drop offers them in a menu (`packageCardNodes`).
 */

type ModelPackage = Parameters<typeof modelInfoRows>[0];

const TRACK = template({ id: "model.curio.sam3/track-objects@1", templateId: "track-objects", label: "Track Objects" });
const SEGMENT = template({
  id: "model.curio.sam3/segment-images@1", templateId: "segment-images", label: "Segment Images",
});

function rowOf(pkg: ModelPackage, label: string) {
  return modelInfoRows(pkg).find((row) => row.label === label);
}

describe("the nodes a model's card makes", () => {
  test("a model package of one node names it under Node", () => {
    const pkg = ddrnetPackage() as ModelPackage;
    expect(rowOf(pkg, "Node")?.value).toBe("Image Segmentation");
    expect(rowOf(pkg, "Nodes")).toBeUndefined();
  });

  test("a model package of two nodes names both under Nodes, in its drop menu's order", () => {
    const pkg = ddrnetPackage({ templates: [TRACK, SEGMENT] }) as ModelPackage;
    expect(modelNodeLabel(pkg)).toBe("Track Objects, Segment Images");
    expect(rowOf(pkg, "Nodes")?.value).toBe("Track Objects, Segment Images");
    expect(rowOf(pkg, "Node")).toBeUndefined();
    // The menu lists a node by its palette order first, then the manifest's.
    const reordered = ddrnetPackage({
      templates: [{ ...TRACK, paletteOrder: 2 }, { ...SEGMENT, paletteOrder: 1 }],
    }) as ModelPackage;
    expect(modelNodeLabel(reordered)).toBe("Segment Images, Track Objects");
  });

  test("a model package with no node has no such row", () => {
    const pkg = ddrnetPackage({ templates: [] }) as ModelPackage;
    expect(modelNodeLabel(pkg)).toBeNull();
    expect(rowOf(pkg, "Node")).toBeUndefined();
    expect(rowOf(pkg, "Nodes")).toBeUndefined();
  });
});
