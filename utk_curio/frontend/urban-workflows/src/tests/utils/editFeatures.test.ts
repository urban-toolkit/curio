/**
 * The Interaction node's edit log (#662; its type is still
 * `curio.builtin/edit-features`): what it keeps, the code it writes from it,
 * the ids a pick on its map names, and the layers it refuses.
 *
 * `editFeaturesCode.cases.json` holds the code for a few logs, other code the
 * node reads, and code it refuses. This checks the node writes exactly that
 * code, reads it back as the log it wrote, and says why it refuses the rest;
 * `utk_curio/sandbox/tests/test_feature_edits.py` reads the same code as Python
 * does and runs it in the sandbox.
 */
import cases from "../../utils/editFeatures/editFeaturesCode.cases.json";
import {
  addPicked,
  defaultKey,
  describeEdit,
  EDIT_CODE_NOTE,
  EDIT_OPS,
  editFeaturesCode,
  readEditFeaturesCode,
  type EditFeaturesRead,
  keyColumns,
  keyRefusal,
  normalizeEdit,
  normalizeEditFeatures,
  pickedIds,
  typedValue,
  withEdit,
  withEditEnabled,
  withNudge,
  withoutEdit,
  type EditFeaturesSettings,
} from "../../utils/editFeatures/editFeatures";
import { VisInteractionType } from "../../constants";

type CodeCase = { name: string; settings: EditFeaturesSettings | null; code: string; circles?: number; comments?: string[] };
type ReadCase = { name: string; code: string; settings: EditFeaturesSettings | null; circles: number; comments: string[] };
type RefusedCase = { name: string; code: string; reason: string };

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
    expect(editFeaturesCode(normalizeEditFeatures(c.settings), c.circles ?? 1, c.comments)).toBe(c.code);
  });

  test("names the edits the sandbox's step makes, in its order", () => {
    // curio_edit_features's OPS is pinned to the same list (test_feature_edits.py).
    expect([...EDIT_OPS]).toEqual(cases.ops);
  });

  test("writes the line breaks Python's splitlines knows as escapes, and no text as a reference", () => {
    const code = editFeaturesCode({ key: "osm_id", edits: [{ op: "set", ids: [1], column: "note", value: `a${String.fromCharCode(0x2028)}b [!! x !!]` }] });
    expect(code).toContain('"value": "a\\u2028b [\\x21! x !!]"');
    expect(readEditFeaturesCode(code)).toMatchObject({ settings: { edits: [{ value: `a${String.fromCharCode(0x2028)}b [!! x !!]` }] } });
  });
});

describe("readEditFeaturesCode", () => {
  // What a read holds, written as the cases write it.
  const asCase = (read: EditFeaturesRead) => {
    if ("problem" in read) throw new Error(read.problem);
    return { settings: read.settings ?? null, circles: read.circles, comments: read.comments };
  };

  test.each((cases.cases as CodeCase[]).map((c) => [c.name, c] as const))("reads back what it wrote: %s", (_name, c) => {
    const read = readEditFeaturesCode(c.code);
    expect(asCase(read)).toEqual({
      settings: normalizeEditFeatures(c.settings) ?? null,
      circles: c.circles ?? 1,
      comments: c.comments ?? EDIT_CODE_NOTE,
    });
    // ...and writes that read as the same code: nothing it reads is lost.
    const back = read as Exclude<EditFeaturesRead, { problem: string }>;
    expect(editFeaturesCode(back.settings, back.circles, back.comments)).toBe(c.code);
  });

  test.each((cases.read as ReadCase[]).map((c) => [c.name, c] as const))("reads code it did not write: %s", (_name, c) => {
    expect(asCase(readEditFeaturesCode(c.code))).toEqual({ settings: normalizeEditFeatures(c.settings) ?? null, circles: c.circles, comments: c.comments });
  });

  test.each((cases.refused as RefusedCase[]).map((c) => [c.name, c] as const))("refuses, saying why: %s", (_name, c) => {
    const read = readEditFeaturesCode(c.code);
    expect(read).toHaveProperty("problem");
    expect((read as { problem: string }).problem).toContain(c.reason);
  });

  test("reads blank code as a new node: no edits, and the circles and comment lines left to the node", () => {
    expect(readEditFeaturesCode("")).toEqual({ settings: undefined });
    expect(readEditFeaturesCode("  \n")).toEqual({ settings: undefined });
  });

  test("reads the code the shipped examples hold", () => {
    const shipped = '# Edit Features writes this code from its edit list: each edit, in the\n# order it was made, on the features whose key is one of its ids. It is\n# written again when the list changes.\nreturn curio_edit_features(input_0, [\n    {"op": "remove", "where": "around_park", "label": "Tall parts around a park"},\n], key="building_id")\n';
    expect(asCase(readEditFeaturesCode(shipped)).settings).toEqual({
      key: "building_id",
      edits: [{ op: "remove", where: "around_park", label: "Tall parts around a park" }],
    });
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
    expect(refusal).toMatch(/The Interaction node matches features by such a column/);
  });
});

describe("the Interaction log", () => {
  test("an entry names its features by ids or by a condition, never both", () => {
    expect(normalizeEdit({ op: "remove", ids: [1], where: "a > 1" })).toBeNull();
    expect(normalizeEdit({ op: "remove" })).toBeNull();
    expect(normalizeEdit({ op: "remove", where: "   " })).toBeNull();
    expect(normalizeEdit({ op: "remove", where: " a > 1 " })).toEqual({ op: "remove", where: "a > 1" });
    expect(normalizeEdit({ op: "scale", where: "height > 100", column: "height", value: 0.5 })).toEqual({
      op: "scale", where: "height > 100", column: "height", value: 0.5,
    });
  });

  test("a scale or an offset takes a number, an expression a text, and each names its column", () => {
    expect(normalizeEdit({ op: "scale", ids: [1], column: "h", value: "2" })).toBeNull();
    expect(normalizeEdit({ op: "offset", ids: [1], column: "h" })).toBeNull();
    expect(normalizeEdit({ op: "offset", ids: [1], value: 3 })).toBeNull();
    expect(normalizeEdit({ op: "expr", ids: [1], column: "h", value: 2 })).toBeNull();
    expect(normalizeEdit({ op: "expr", ids: [1], column: "h", value: "levels * 3" })).toEqual({
      op: "expr", ids: [1], column: "h", value: "levels * 3",
    });
    expect(normalizeEdit({ op: "offset", ids: [1, 1], column: "h", value: -3 })).toEqual({ op: "offset", ids: [1], column: "h", value: -3 });
  });

  test("an entry keeps its label and its switch, and writes the switch only when off", () => {
    expect(normalizeEdit({ op: "remove", ids: [1], label: " Tower ", enabled: false })).toEqual({
      op: "remove", ids: [1], label: "Tower", enabled: false,
    });
    expect(normalizeEdit({ op: "remove", ids: [1], label: "", enabled: true })).toEqual({ op: "remove", ids: [1] });
  });

  test("an entry is switched off and on again by its place", () => {
    const settings: EditFeaturesSettings = {
      key: "id",
      edits: [{ op: "remove", ids: [1] }, { op: "offset", ids: [2], column: "h", value: 1 }],
    };
    const off = withEditEnabled(settings, 0, false);
    expect(off?.edits).toEqual([{ op: "remove", ids: [1], enabled: false }, { op: "offset", ids: [2], column: "h", value: 1 }]);
    expect(withEditEnabled(off, 0, true)).toEqual(settings);
  });

  test("presses of an arrow on one pick fold into one entry, and a nudge back to nothing drops it", () => {
    const up = { op: "offset" as const, ids: [7], column: "height", value: 3 };
    let settings: EditFeaturesSettings | undefined = { key: "id" };
    settings = withNudge(settings, up);
    settings = withNudge(settings, up);
    expect(settings.edits).toEqual([{ op: "offset", ids: [7], column: "height", value: 6 }]);
    // Another pick is another entry.
    settings = withNudge(settings, { ...up, ids: [8] });
    expect(settings.edits).toHaveLength(2);
    settings = withNudge(settings, { ...up, ids: [8], value: -3 });
    expect(settings.edits).toEqual([{ op: "offset", ids: [7], column: "height", value: 6 }]);
    // Sums keep 15 significant digits.
    expect(withNudge(withNudge({ key: "id" }, { ...up, value: 0.1 }), { ...up, value: 0.2 }).edits).toEqual([
      { op: "offset", ids: [7], column: "height", value: 0.3 },
    ]);
    // An entry switched off, or one with a label, is never folded into.
    const off = withNudge({ key: "id", edits: [{ ...up, enabled: false }] }, up);
    expect(off.edits).toEqual([{ ...up, enabled: false }, up]);
    const labelled = withNudge({ key: "id", edits: [{ ...up, label: "Tower" }] }, up);
    expect(labelled.edits).toEqual([{ ...up, label: "Tower" }, up]);
  });

  test("each entry reads as a sentence, the ones a pick makes as before", () => {
    expect(describeEdit({ op: "remove", ids: [119, 136] }, "building_id")).toBe("Remove building_id 119, 136");
    expect(describeEdit({ op: "set", ids: ["w7"], column: "height", value: 30 }, "osm_id")).toBe("Set height to 30 on osm_id w7");
    expect(describeEdit({ op: "remove", where: "height > 100" }, "building_id")).toBe("Remove where height > 100");
    expect(describeEdit({ op: "restore", where: "kind == 'tower'" }, "building_id")).toBe("Restore where kind == 'tower'");
    expect(describeEdit({ op: "set", where: "kind == 'house'", column: "kind", value: "home" }, "osm_id")).toBe(
      "Set kind to home where kind == 'house'",
    );
    expect(describeEdit({ op: "scale", where: "height > 100", column: "height", value: 0.5 }, "building_id")).toBe(
      "Scale height by 0.5 where height > 100",
    );
    expect(describeEdit({ op: "offset", ids: [3], column: "height", value: 6 }, "building_id")).toBe("Raise height by 6 on building_id 3");
    expect(describeEdit({ op: "offset", ids: [3], column: "height", value: -6 }, "building_id")).toBe("Lower height by 6 on building_id 3");
    expect(describeEdit({ op: "expr", ids: [1], column: "height", value: "levels * 3.2" }, "osm_id")).toBe(
      "Compute height as levels * 3.2 on osm_id 1",
    );
    expect(describeEdit({ op: "remove", ids: [1, 2], label: "Towers" }, "building_id")).toBe("Towers: Remove building_id 1, 2");
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
