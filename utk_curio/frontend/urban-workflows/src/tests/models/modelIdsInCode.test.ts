/**
 * `modelIdsInCode`: the literal `curio_model("<id>")` calls in a node's code,
 * the frontend half of `MODEL_CALL_RE` / `model_ids_in_code` in
 * `backend/app/datasets/domain/code_refs.py`.
 */
import { modelIdsInCode } from "../../services/modelCatalog";
import { datasetIdsInCode } from "../../services/datasetCatalog/datasetLoaderSnippets";

describe("modelIdsInCode", () => {
  test("finds a call in either quote style", () => {
    expect(modelIdsInCode('folder = curio_model("model.curio.ddrnet23-slim")')).toEqual([
      "model.curio.ddrnet23-slim",
    ]);
    expect(modelIdsInCode("folder = curio_model('imported.xabc@1')")).toEqual(["imported.xabc@1"]);
  });

  test("allows spaces inside the parentheses", () => {
    expect(modelIdsInCode('curio_model(  "a.b"  )')).toEqual(["a.b"]);
  });

  test("a mismatched pair of quotes names nothing", () => {
    expect(modelIdsInCode(`curio_model("a.b')`)).toEqual([]);
  });

  test("an id outside the charset names nothing", () => {
    expect(modelIdsInCode('curio_model("has space")')).toEqual([]);
    expect(modelIdsInCode('curio_model(".leading-dot")')).toEqual([]);
    expect(modelIdsInCode('curio_model("")')).toEqual([]);
    expect(modelIdsInCode("curio_model(model_id)")).toEqual([]);
  });

  test("first seen first, each id once", () => {
    const code = [
      'a = curio_model("m.two")',
      "b = curio_model('m.one')",
      'c = curio_model("m.two")',
    ].join("\n");
    expect(modelIdsInCode(code)).toEqual(["m.two", "m.one"]);
  });

  test("stops at eight, the backend's bound", () => {
    const code = Array.from({ length: 12 }, (_, i) => `curio_model("m.n${i}")`).join("\n");
    const ids = modelIdsInCode(code);
    expect(ids).toHaveLength(8);
    expect(ids[0]).toBe("m.n0");
    expect(ids[7]).toBe("m.n7");
  });

  test("anything that is not a string names nothing", () => {
    expect(modelIdsInCode(undefined)).toEqual([]);
    expect(modelIdsInCode(null)).toEqual([]);
    expect(modelIdsInCode(42)).toEqual([]);
    expect(modelIdsInCode("")).toEqual([]);
  });

  test("the two grammars stay apart", () => {
    // A model is not a dataset: neither scanner reads the other's call.
    const code = 'p = curio_dataset_path("data.x")\nm = curio_model("model.y")';
    expect(modelIdsInCode(code)).toEqual(["model.y"]);
    expect(datasetIdsInCode(code)).toEqual(["data.x"]);
  });
});
