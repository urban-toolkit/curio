/**
 * A model package's card, dragged from the Model Catalog drawer or the
 * Models palette (PR #819 port, step 4.5).
 *
 * - Onto the canvas it is its package's card: the drop goes through the Node
 *   Catalog's card drop (`usePackageCardDrop`), and the node it makes opens
 *   with its template's code, which for a template without a `source` is the
 *   default cell of the model's type, naming the model.
 * - Onto a node it swaps the node's model within one type, and is refused
 *   across types.
 *
 * Reached through `require`, so a checkout without them fails test by test.
 */
import React from "react";
import { act, render } from "@testing-library/react";

import { usePackageCardDrop, type PackageCardDrop } from "../../components/packages/usePackageCardDrop";
import {
  guestAddRefusal,
  usePackageAddRequests,
  type PackageAddRequest,
} from "../../services/packages/packageAddRequests";
import * as fs from "fs";
import * as path from "path";

import { ddrnetPackage, deepUmbraPackage, importedModelPackage } from "../_support/modelPackages";

/** A source file under `src/`. */
const read = (rel: string) => fs.readFileSync(path.join(__dirname, "..", "..", rel), "utf8");

// eslint-disable-next-line @typescript-eslint/no-var-requires
const {
  applyModelToNodeData,
  createModelDragPayload,
  endModelCardDrag,
  modelSwapRefusal,
  nodeModelType,
  nodesNamingModelInCodeOnly,
  packageCardNodeOptions,
  readModelDragPayload,
  readPackageCardDragPayload,
  renameModelCalls,
  writeModelCardDrag,
} = require("../../services/packages");

/** A minimal DataTransfer: jsdom has none. */
function fakeDataTransfer() {
  const store = new Map<string, string>();
  return {
    effectAllowed: "",
    get types() {
      return Array.from(store.keys());
    },
    setData: (type: string, value: string) => void store.set(type, value),
    getData: (type: string) => store.get(type) ?? "",
  } as unknown as DataTransfer;
}

/** The cell the backend writes for a segmentation model's node (`domain/default_cells.py`). */
function segmentationCell(modelId: string): string {
  return (
    `model = curio_load_model("${modelId}")\n` +
    "classes = None  # every class the model names\n" +
    "\n" +
    "return curio_segment(input_0, model, classes)\n"
  );
}

afterEach(() => endModelCardDrag?.());

describe("a model card's drag", () => {
  test("carries the model, with its type, for a node, and its package's one node for the canvas", () => {
    const dataTransfer = fakeDataTransfer();
    writeModelCardDrag(dataTransfer, ddrnetPackage());
    endModelCardDrag();

    // Read back from the DataTransfer alone, once the in-memory drag has ended.
    expect(readModelDragPayload(dataTransfer)).toEqual({
      modelId: "model.curio.ddrnet23-slim",
      name: "DDRNet23-Slim (street scenes)",
      runtime: "onnx",
      type: "semantic-segmentation",
    });
    expect(readPackageCardDragPayload(dataTransfer)).toEqual({
      dirName: "model.curio.ddrnet23-slim@1",
      name: "DDRNet23-Slim (street scenes)",
      kind: "model",
      nodes: [{
        nodeType: "model.curio.ddrnet23-slim/image-segmentation@1",
        label: "Image Segmentation",
        model: { id: "model.curio.ddrnet23-slim", name: "DDRNet23-Slim (street scenes)" },
      }],
    });
    expect(dataTransfer.effectAllowed).toBe("copy");
  });
});

describe("the node a model card's drop makes", () => {
  /** DDRNet23-Slim's one node, as its card's drag carries it. */
  function ddrnetNode() {
    const dataTransfer = fakeDataTransfer();
    writeModelCardDrag(dataTransfer, ddrnetPackage());
    const card = readPackageCardDragPayload(dataTransfer);
    endModelCardDrag();
    return card.nodes[0];
  }

  test("opens with its type's default cell, which names the model, and is bound to it", () => {
    const cell = segmentationCell("model.curio.ddrnet23-slim");
    expect(packageCardNodeOptions(ddrnetNode(), cell)).toEqual({
      code: cell,
      modelRefs: [{ id: "model.curio.ddrnet23-slim", name: "DDRNet23-Slim (street scenes)" }],
    });
  });

  test("names its own model when its template's call names another or none", () => {
    expect(packageCardNodeOptions(ddrnetNode(), segmentationCell("")).code).toBe(
      segmentationCell("model.curio.ddrnet23-slim"),
    );
    expect(packageCardNodeOptions(ddrnetNode(), segmentationCell("model.other")).code).toBe(
      segmentationCell("model.curio.ddrnet23-slim"),
    );
  });

  test("is bound to its model before its template's code has arrived", () => {
    expect(packageCardNodeOptions(ddrnetNode(), undefined)).toEqual({
      modelRefs: [{ id: "model.curio.ddrnet23-slim", name: "DDRNet23-Slim (street scenes)" }],
    });
  });

  test("of a node package opens with its template's code as a palette drop does", () => {
    expect(packageCardNodeOptions({ nodeType: "pkg/node@1", label: "Node" }, "return 1")).toEqual({});
  });
});

describe("a model card dropped on the canvas goes through the Node Catalog's card drop", () => {
  /** A canvas as MainCanvas renders it; *more* adds to the drop's options. */
  function canvas(added: string[] = [], more: Record<string, unknown> = {}) {
    const createNode = jest.fn();
    const showToast = jest.fn();
    let drop: (dropped: PackageCardDrop) => void = () => undefined;
    function Canvas() {
      const options: any = { dataflowPackages: added, hostedGuest: false, createNode, showToast, ...more };
      const cardDrop = usePackageCardDrop(options);
      drop = cardDrop.drop;
      return <>{cardDrop.menu}</>;
    }
    render(<Canvas />);
    const dataTransfer = fakeDataTransfer();
    writeModelCardDrag(dataTransfer, deepUmbraPackage());
    const card = readPackageCardDragPayload(dataTransfer);
    endModelCardDrag();
    return {
      createNode,
      showToast,
      card,
      drop: () => act(() => drop({ card, position: { x: 1, y: 2 }, at: { x: 3, y: 4 } })),
    };
  }

  test("makes the model's node once the Model Catalog drawer's Add has added its package", () => {
    const requests: PackageAddRequest[] = [];
    function ModelDrawer() {
      usePackageAddRequests((request) => {
        if (request.kind !== "model") return false;
        requests.push(request);
        return true;
      });
      return null;
    }
    render(<ModelDrawer />);
    const { createNode, card, drop } = canvas();
    drop();
    expect(requests.map((r) => [r.dirName, r.kind])).toEqual([["model.scout.deep-umbra@1", "model"]]);
    expect(createNode).not.toHaveBeenCalled();
    act(() => requests[0].onAdded());
    expect(createNode).toHaveBeenCalledWith(card.nodes[0], { x: 1, y: 2 });
  });

  test("with no Model Catalog drawer open, says to add the model from the Model Catalog", () => {
    const { createNode, showToast, drop } = canvas();
    drop();
    expect(createNode).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(
      "Add Deep Umbra (accumulated shadows) to this dataflow from the Model Catalog first.",
      "warning",
    );
  });

  /** An open Model Catalog drawer that takes every Add asked of it, and the
   *  Adds it was asked for. */
  function openModelDrawer(): PackageAddRequest[] {
    const requests: PackageAddRequest[] = [];
    function ModelDrawer() {
      usePackageAddRequests((request) => {
        requests.push(request);
        return true;
      });
      return null;
    }
    render(<ModelDrawer />);
    return requests;
  }

  test("of a model the dataflow declares, as every Models dropdown row is, makes its node at once, with no Add", () => {
    // The dropdown lists only the dataflow's models (ModelsPaletteDropdown.test.tsx).
    const requests = openModelDrawer();
    const { createNode, showToast, card, drop } = canvas(["curio.builtin@1", "model.scout.deep-umbra@1"]);
    drop();
    expect(createNode).toHaveBeenCalledTimes(1);
    expect(createNode).toHaveBeenCalledWith(card.nodes[0], { x: 1, y: 2 });
    expect(requests).toEqual([]);
    expect(showToast).not.toHaveBeenCalled();
  });

  test("a hosted guest's drop of a model the dataflow lacks is refused before any drawer is asked", () => {
    const requests = openModelDrawer();
    const { createNode, showToast, drop } = canvas([], { hostedGuest: true });
    drop();
    expect(showToast).toHaveBeenCalledWith(guestAddRefusal("Deep Umbra (accumulated shadows)"), "warning");
    expect(requests).toEqual([]);
    expect(createNode).not.toHaveBeenCalled();
  });
});

describe("a node saved as a model package", () => {
  test("names the new package wherever its code named the model it copied", () => {
    const code =
      'a = curio_load_model("model.example.local-relief")\n' +
      "b = curio_load_model( 'model.example.local-relief' )\n" +
      'c = curio_load_model("model.example.local-relief-2")\n';
    expect(renameModelCalls(code, "model.example.local-relief", "curio.canvas.draft.relief")).toBe(
      'a = curio_load_model("curio.canvas.draft.relief")\n' +
        "b = curio_load_model( 'curio.canvas.draft.relief' )\n" +
        'c = curio_load_model("model.example.local-relief-2")\n',
    );
    expect(renameModelCalls(code, "model.example.local-relief", 'bad")\nimport os')).toBe(code);
  });
});

describe("a model dropped on a node", () => {
  const segmentationNode = { code: segmentationCell("model.curio.ddrnet23-slim") };
  const types: Record<string, string> = {
    "model.curio.ddrnet23-slim": "semantic-segmentation",
    "model.scout.deep-umbra": "image-to-image",
  };
  const typeOf = (id: string) => types[id];

  test("the node's type is the type of the model its code names, else its own package's", () => {
    expect(nodeModelType(segmentationNode, typeOf)).toBe("semantic-segmentation");
    expect(nodeModelType({ code: segmentationCell("") }, typeOf, "image-to-image")).toBe("image-to-image");
    expect(nodeModelType({ code: segmentationCell("model.nowhere") }, typeOf)).toBeUndefined();
  });

  test("of the node's type takes the node's model", () => {
    const segformer = createModelDragPayload(importedModelPackage());
    expect(modelSwapRefusal(nodeModelType(segmentationNode, typeOf), segformer)).toBeNull();
    expect(applyModelToNodeData(segmentationNode, segformer).code).toBe(segmentationCell("imported.xabc123def456"));
  });

  test("of another type is refused, saying both types", () => {
    const deepUmbra = createModelDragPayload(deepUmbraPackage());
    expect(modelSwapRefusal(nodeModelType(segmentationNode, typeOf), deepUmbra)).toBe(
      "This node runs semantic segmentation models, and Deep Umbra (accumulated shadows) is an image to image model.",
    );
  });

  test("whose node's type is not known is refused, saying so", () => {
    const deepUmbra = createModelDragPayload(deepUmbraPackage());
    const refusal = "This node's model type is unknown, so it does not take Deep Umbra (accumulated shadows).";
    expect(modelSwapRefusal(undefined, deepUmbra)).toBe(refusal);
    expect(modelSwapRefusal(nodeModelType({ code: segmentationCell("model.nowhere") }, typeOf), deepUmbra)).toBe(
      refusal,
    );
  });

  test("whose own type is not known is refused, saying so", () => {
    // A model block without a type: its drag carries none.
    const untyped = createModelDragPayload({ ...importedModelPackage(), model: { runtime: "onnx" } });
    expect(untyped.type).toBeUndefined();
    expect(modelSwapRefusal("semantic-segmentation", untyped)).toBe(
      "The model type of SegFormer B0 (ADE20K) is unknown, so this node does not take it.",
    );
    // Neither known: the node's is said first.
    expect(modelSwapRefusal(undefined, untyped)).toBe(
      "This node's model type is unknown, so it does not take SegFormer B0 (ADE20K).",
    );
  });

  test("binds the node, and a node bound to a model is not one that names it in code alone", () => {
    const relief = "model.example.local-relief";
    const call = `m = curio_load_model("${relief}")`;
    const nodes = [
      { id: "own", data: { nodeType: `${relief}/local-relief@1`, code: call } },
      { id: "bound", data: { nodeType: "curio.builtin/computation-analysis@1", code: call,
                              modelRefs: [{ id: relief, name: "Local Relief (example)" }] } },
      { id: "in-code-only", data: { nodeType: "curio.builtin/computation-analysis@1", code: call } },
      { id: "template-only", data: { nodeType: "curio.builtin/computation-analysis@1", defaultCode: call } },
      { id: "other", data: { nodeType: "curio.builtin/computation-analysis@1",
                             code: 'm = curio_load_model("model.curio.ddrnet23-slim")' } },
    ];
    expect(nodesNamingModelInCodeOnly(nodes, relief)).toEqual(["in-code-only", "template-only"]);
  });

  test("is refused by the node's drop handler before any model is applied", () => {
    const styles = read("components/styles.tsx");
    const handler = styles.slice(styles.indexOf("modelDropHandlerRef.current = (e: DragEvent) => {"));
    const refusal = handler.indexOf("modelSwapRefusal(");
    expect(refusal).toBeGreaterThan(-1);
    expect(refusal).toBeLessThan(handler.indexOf("applyModelToNodeData(live, model)"));
    expect(handler.slice(refusal, handler.indexOf("applyModelToNodeData(live, model)"))).toContain(
      'showToast(refused, "warning")',
    );
  });
});
