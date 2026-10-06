/**
 * The Edit Features node's edit list (#662): what it keeps, the code it writes
 * from it, the ids a pick on its map names, and the layers it refuses.
 *
 * `editFeaturesCode.cases.json` holds the code for a few lists. This checks
 * the node writes exactly that; `utk_curio/sandbox/tests/test_feature_edits.py`
 * runs the same code in the sandbox.
 */
import cases from "../../utils/editFeatures/editFeaturesCode.cases.json";
import {
  addPicked,
  defaultKey,
  describeEdit,
  editFeaturesCode,
  isEditFeaturesNode,
  keyColumns,
  keyRefusal,
  normalizeEditFeatures,
  pickedIds,
  typedValue,
  withEdit,
  withoutEdit,
  type EditFeaturesSettings,
} from "../../utils/editFeatures/editFeatures";
import { CURIO_UNIVERSAL_NODE_TYPE, VisInteractionType } from "../../constants";

type CodeCase = { name: string; settings: EditFeaturesSettings | null; code: string };

/** Autark's buildings: a building's parts share its building_id, and none has an osm_id. */
function buildings() {
  const part = (building_id: number, height: number, name?: string) => ({
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
    properties: { building_id, height, ...(name ? { name } : {}) },
  });
  // Heights repeat, so height identifies nothing.
  return { type: "FeatureCollection", features: [part(119, 240.8, "200 Clarendon"), part(119, 60), part(136, 136), part(7, 60)] };
}

/** What an Autark map reports for a pick: the input rows it names, on its pickable layer. */
const pickOf = (rows: number[]) => ({
  autk_selection: { type: VisInteractionType.POINT, data: rows, priority: 1, layerRef: "table_osm_buildings" },
});

describe("editFeaturesCode", () => {
  test.each((cases.cases as CodeCase[]).map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(editFeaturesCode(normalizeEditFeatures(c.settings))).toBe(c.code);
  });
});

describe("the edit list", () => {
  test("keeps well-formed edits, each id once, and nothing else", () => {
    expect(
      normalizeEditFeatures({
        key: "building_id",
        layer: "table_osm_buildings",
        edits: [
          { op: "remove", ids: [119, 119, "w7", { row: 2 }] },
          { op: "set", ids: [7], column: "height", value: 0 },
          { op: "set", ids: [7], value: 0 },
          { op: "delete", ids: [7] },
          { op: "restore", ids: [] },
        ],
        rows: [3],
      }),
    ).toEqual({
      key: "building_id",
      layer: "table_osm_buildings",
      edits: [
        { op: "remove", ids: [119, "w7"] },
        { op: "set", ids: [7], column: "height", value: 0 },
      ],
    });
  });

  test("is undefined when nothing is left, so nothing is written", () => {
    expect(normalizeEditFeatures(undefined)).toBeUndefined();
    expect(normalizeEditFeatures({ key: "", edits: [{ op: "remove", ids: [] }] })).toBeUndefined();
  });

  test("an edit is added after the others, and deleted by its place", () => {
    const one = withEdit({ key: "building_id" }, { op: "remove", ids: [119] });
    const two = withEdit(one, { op: "set", ids: [7], column: "height", value: 3 });
    expect(two.edits?.map((e) => e.op)).toEqual(["remove", "set"]);
    expect(withoutEdit(two, 0)).toEqual({ key: "building_id", edits: [{ op: "set", ids: [7], column: "height", value: 3 }] });
    expect(withoutEdit(one, 0)).toEqual({ key: "building_id" });
  });

  test("each edit reads as a line naming the features by their key", () => {
    expect(describeEdit({ op: "remove", ids: [119, 136] }, "building_id")).toBe("Remove building_id 119, 136");
    expect(describeEdit({ op: "restore", ids: [136] }, "building_id")).toBe("Restore building_id 136");
    expect(describeEdit({ op: "set", ids: ["w7"], column: "height", value: 30 }, "osm_id")).toBe("Set height to 30 on osm_id w7");
  });

  test("is an Edit Features node's, by its type", () => {
    const node = (nodeType: string) => ({ type: CURIO_UNIVERSAL_NODE_TYPE, data: { nodeType } });
    expect(isEditFeaturesNode(node("curio.builtin/edit-features@1"))).toBe(true);
    expect(isEditFeaturesNode(node("curio.builtin/edit-features"))).toBe(true);
    expect(isEditFeaturesNode(node("curio.builtin/compare-scenarios@1"))).toBe(false);
  });
});

describe("picking on the map", () => {
  test("a pick names the picked features' ids, and each pick adds to the list", () => {
    const fc = buildings();
    // Both parts of 200 Clarendon, by their rows: one id.
    const first = pickedIds(pickOf([0, 1]), fc, "building_id");
    expect(first).toEqual([119]);
    let picked = addPicked([], first);
    picked = addPicked(picked, pickedIds(pickOf([2]), fc, "building_id"));
    picked = addPicked(picked, pickedIds(pickOf([1]), fc, "building_id"));
    expect(picked).toEqual([119, 136]);
    // The edit made from the pick names those ids.
    expect(withEdit(undefined, { op: "remove", ids: picked }).edits).toEqual([{ op: "remove", ids: [119, 136] }]);
  });

  test("a pick of nothing names nothing", () => {
    expect(pickedIds(pickOf([]), buildings(), "building_id")).toEqual([]);
    expect(pickedIds(null, buildings(), "building_id")).toEqual([]);
  });
});

describe("which column identifies a feature", () => {
  test("osm_id or building_id when the layer has one, with any column unique in every feature", () => {
    const fc = buildings();
    // building_id repeats across a building's parts and is still the key.
    expect(keyColumns(fc)).toEqual(["building_id"]);
    expect(defaultKey(keyColumns(fc))).toBe("building_id");
    const named = {
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: null, properties: { code: "a", kind: "x" } },
        { type: "Feature", geometry: null, properties: { code: "b", kind: "x" } },
      ],
    };
    expect(keyColumns(named)).toEqual(["code"]);
    expect(defaultKey(keyColumns(named))).toBeUndefined();
    expect(keyRefusal(keyColumns(named), "parcels")).toBeNull();
  });

  test("a layer with no such column is refused, and a row's place is never one", () => {
    const placesOnly = {
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: null, properties: { __row_index__: 0, kind: "x", interacted: "0" } },
        { type: "Feature", geometry: null, properties: { __row_index__: 1, kind: "x", interacted: "0" } },
      ],
    };
    expect(keyColumns(placesOnly)).toEqual([]);
    const refusal = keyRefusal(keyColumns(placesOnly), "parcels");
    expect(refusal).toMatch(/^parcels has no column that identifies its features/);
    expect(refusal).toMatch(/never by their place in the layer/);
  });
});

describe("Set value", () => {
  test("reads a number for a column of numbers, and text otherwise", () => {
    const fc = buildings();
    expect(typedValue("30", fc, "height")).toBe(30);
    expect(typedValue("tall", fc, "height")).toBeUndefined();
    expect(typedValue("Tower B", fc, "name")).toBe("Tower B");
    expect(typedValue("x", fc, "new_column")).toBe("x");
  });
});
