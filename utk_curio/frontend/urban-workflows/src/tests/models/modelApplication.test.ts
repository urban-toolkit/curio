/**
 * Setting a node's model by dropping one on it.
 *
 * A node runs a model by naming it in `curio_model("<id>")`; a drop rewrites
 * that name and records which model it is (`modelRefs`, saved at
 * `metadata.modelRefs`). Pure functions, so they are tested as such.
 */
import {
  MODEL_DRAG_MIME,
  applyModelToNodeData,
  beginModelDrag,
  canApplyModelToNode,
  endModelDrag,
  hasModelDrag,
  modelNodeForCanvas,
  nodeLinkedModelIds,
  readModelDragPayload,
  writeModelDragData,
} from "../../services/modelCatalog";
import { TrillGenerator } from "../../TrillGenerator";
import { downloadedModel, shippedModel } from "../_support/modelRows";

const ddrnet = { id: "model.curio.ddrnet23-slim", name: "DDRNet23-Slim (street scenes)" };
const segformer = { id: "imported.xabc123def456", name: "SegFormer B0 (ADE20K)" };

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

afterEach(() => endModelDrag());

describe("canApplyModelToNode", () => {
  test("a node whose code calls curio_model can take a model", () => {
    expect(canApplyModelToNode({ code: 'm = curio_model("model.x")' })).toBe(true);
    expect(canApplyModelToNode({ code: "m = curio_model('model.x')" })).toBe(true);
  });

  test("a template's default code counts until the node has its own", () => {
    expect(canApplyModelToNode({ defaultCode: 'curio_model("model.x")' })).toBe(true);
  });

  test("the node's own code wins over its template's", () => {
    // The drop rewrites the code the node runs, so that is the code asked.
    expect(
      canApplyModelToNode({ code: "return 1", defaultCode: 'curio_model("model.x")' }),
    ).toBe(false);
  });

  test("a placeholder string is still a call a drop can fill", () => {
    expect(canApplyModelToNode({ code: 'curio_model("")' })).toBe(true);
  });

  test("a node that never calls curio_model cannot", () => {
    expect(canApplyModelToNode({ code: "return input_1" })).toBe(false);
    expect(canApplyModelToNode({ code: "curio_model(model_id)" })).toBe(false);
    expect(canApplyModelToNode({})).toBe(false);
    expect(canApplyModelToNode(undefined)).toBe(false);
  });
});

describe("applyModelToNodeData", () => {
  test("rewrites the id in a double-quoted call and keeps the quotes", () => {
    const data = { nodeId: "n1", code: 'folder = curio_model("old.model")\nrun(folder)' };
    const next = applyModelToNodeData(data, ddrnet);
    expect(next.code).toBe('folder = curio_model("model.curio.ddrnet23-slim")\nrun(folder)');
    expect(next.defaultCode).toBe(next.code);
  });

  test("rewrites a single-quoted call in single quotes", () => {
    const next = applyModelToNodeData({ code: "f = curio_model('old.model')" }, ddrnet);
    expect(next.code).toBe("f = curio_model('model.curio.ddrnet23-slim')");
  });

  test("keeps the spacing inside the parentheses", () => {
    const next = applyModelToNodeData({ code: 'f = curio_model( "old" )' }, ddrnet);
    expect(next.code).toBe('f = curio_model( "model.curio.ddrnet23-slim" )');
  });

  test("only the first call changes", () => {
    const code = 'a = curio_model("one")\nb = curio_model(\'two\')';
    const next = applyModelToNodeData({ code }, ddrnet);
    expect(next.code).toBe('a = curio_model("model.curio.ddrnet23-slim")\nb = curio_model(\'two\')');
  });

  test("fills a template's placeholder", () => {
    const next = applyModelToNodeData({ defaultCode: 'm = curio_model("")' }, segformer);
    expect(next.code).toBe('m = curio_model("imported.xabc123def456")');
  });

  test("records the one model the node now runs, replacing any before", () => {
    const first = applyModelToNodeData({ code: 'curio_model("x")' }, ddrnet);
    expect(first.modelRefs).toEqual([{ id: ddrnet.id, name: ddrnet.name }]);
    const second = applyModelToNodeData(first, segformer);
    expect(second.modelRefs).toEqual([{ id: segformer.id, name: segformer.name }]);
  });

  test("a node with no call comes back unchanged, the same object", () => {
    const data = { nodeId: "n1", code: "return input_1" };
    expect(applyModelToNodeData(data, ddrnet)).toBe(data);
    const empty = { nodeId: "n2" };
    expect(applyModelToNodeData(empty, ddrnet)).toBe(empty);
  });

  test("an id that is not safe to write into source changes nothing", () => {
    const data = { code: 'curio_model("x")' };
    expect(applyModelToNodeData(data, { id: 'bad")\nimport os', name: "bad" })).toBe(data);
  });

  test("leaves the input alone", () => {
    const data = { code: 'curio_model("x")', other: 1 };
    applyModelToNodeData(data, ddrnet);
    expect(data).toEqual({ code: 'curio_model("x")', other: 1 });
  });

  test("takes a drag payload as well as a row", () => {
    const next = applyModelToNodeData(
      { code: 'curio_model("x")' },
      { modelId: ddrnet.id, name: ddrnet.name, runtime: "onnx" },
    );
    expect(next.code).toBe('curio_model("model.curio.ddrnet23-slim")');
  });
});

describe("modelNodeForCanvas", () => {
  const segmentation = {
    nodeType: "curio.streetvision/image-segmentation@1",
    label: "Image Segmentation",
    code: 'model = curio_model("model.curio.ddrnet23-slim")\nreturn curio_segment(arg, model)',
    packageName: "Street Vision",
  };
  const loader = { nodeType: "curio.builtin/data-loading", label: "Data Loading", code: undefined };
  const transform = { nodeType: "x.pkg/transform@1", label: "Transform", code: "return arg" };

  test("a model dropped on the canvas becomes the first template that runs one", () => {
    const node = modelNodeForCanvas([loader, transform, segmentation], segformer);
    expect(node).toEqual({
      ...segmentation,
      code: 'model = curio_model("imported.xabc123def456")\nreturn curio_segment(arg, model)',
      modelRefs: [{ id: segformer.id, name: segformer.name }],
    });
  });

  test("its code is what a drop on that node would write", () => {
    const node = modelNodeForCanvas([segmentation], ddrnet);
    expect(node?.code).toBe(applyModelToNodeData({ code: segmentation.code }, ddrnet).code);
  });

  test("takes a drag payload as well as a row", () => {
    const node = modelNodeForCanvas(
      [segmentation],
      { modelId: segformer.id, name: segformer.name, runtime: "transformers" },
    );
    expect(node?.modelRefs).toEqual([{ id: segformer.id, name: segformer.name }]);
  });

  test("no template that runs a model makes nothing", () => {
    expect(modelNodeForCanvas([loader, transform], ddrnet)).toBeNull();
    expect(modelNodeForCanvas([], ddrnet)).toBeNull();
  });

  test("an id that is not safe to write into source makes nothing", () => {
    expect(modelNodeForCanvas([segmentation], { id: 'bad")\nimport os', name: "bad" })).toBeNull();
  });
});

describe("the model drag", () => {
  test("round-trips through the custom type and the text fallback", () => {
    const dt = fakeDataTransfer();
    writeModelDragData(dt, beginModelDrag(shippedModel()));
    expect(dt.effectAllowed).toBe("copy");
    expect(hasModelDrag(dt)).toBe(true);
    expect(JSON.parse(dt.getData(MODEL_DRAG_MIME))).toEqual({
      modelId: "model.curio.ddrnet23-slim",
      name: "DDRNet23-Slim (street scenes)",
      runtime: "onnx",
    });
    // A new page (no in-memory payload) still reads it, from either form.
    endModelDrag();
    expect(readModelDragPayload(dt)?.modelId).toBe("model.curio.ddrnet23-slim");
    const plainOnly = fakeDataTransfer();
    plainOnly.setData("text/plain", dt.getData("text/plain"));
    expect(readModelDragPayload(plainOnly)?.name).toBe("DDRNet23-Slim (street scenes)");
  });

  test("a dataset or node drag is not a model drag", () => {
    const dt = fakeDataTransfer();
    dt.setData("application/x-curio-dataset", "{}");
    dt.setData("text/plain", "curio-dataset:{}");
    expect(hasModelDrag(dt)).toBe(false);
    expect(readModelDragPayload(dt)).toBeNull();
  });
});

describe("nodeLinkedModelIds", () => {
  test("reads the drop's binding and every literal call", () => {
    expect(
      nodeLinkedModelIds({
        modelRefs: [{ id: "m.bound", name: "Bound" }],
        code: 'curio_model("m.code")',
        defaultCode: "curio_model('m.template')",
      }),
    ).toEqual(["m.bound", "m.code", "m.template"]);
  });
});

describe("the saved dataflow says which model a node runs", () => {
  beforeEach(() => TrillGenerator.reset());

  test("modelRefs is saved at metadata.modelRefs, and only when set", () => {
    const applied = applyModelToNodeData(
      { nodeId: "seg-1", nodeType: "curio.builtin/computation-analysis", code: 'curio_model("x")' },
      downloadedModel(),
    );
    const spec = TrillGenerator.generateTrill(
      [
        { type: "CURIO_UNIVERSAL_NODE", position: { x: 0, y: 0 }, data: applied },
        {
          type: "CURIO_UNIVERSAL_NODE",
          position: { x: 5, y: 5 },
          data: { nodeId: "plain-1", nodeType: "curio.builtin/computation-analysis" },
        },
      ],
      [],
      "Imported Workflow",
    );
    const byId = Object.fromEntries(spec.dataflow.nodes.map((n: any) => [n.id, n]));
    expect(byId["seg-1"].metadata.modelRefs).toEqual([
      { id: "imported.xabc123def456", name: "SegFormer B0 (ADE20K)" },
    ]);
    expect(byId["seg-1"].content).toBe('curio_model("imported.xabc123def456")');
    expect(byId["plain-1"].metadata).toBeUndefined();
  });
});
