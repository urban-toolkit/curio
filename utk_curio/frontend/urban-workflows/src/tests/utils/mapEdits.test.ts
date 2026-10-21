/**
 * The Map Edits node's edits (`utils/mapEdits/mapEdits.ts`): the code it
 * writes from them and reads back, the change an Apply in its properties
 * panel makes, the helpers its panel and its Provenance entries call, and the
 * features its map draws.
 *
 * `mapEditsCode.cases.json` and `mapEditsApply.cases.json` hold cases that
 * `utk_curio/sandbox/tests/test_map_edits.py` checks too: Python reads each
 * code's arguments as the same edits, and the sandbox's `curio_map_edits`
 * leaves the same features the map draws.
 */
import codeCases from "../../utils/mapEdits/mapEditsCode.cases.json";
import applyCases from "../../utils/mapEdits/mapEditsApply.cases.json";
import {
  MAP_EDITS_HELPER,
  applyMapEdits,
  changeFor,
  changeFromField,
  changeLabel,
  isFeatureId,
  isRemoved,
  mapEditsCode,
  mapEditsComment,
  putBackLabel,
  readMapEdits,
  removeLabel,
  sameId,
  withChange,
  withPutBack,
  withRemoved,
  type MapEdits,
  type MapFeature,
} from "../../utils/mapEdits/mapEdits";

type CodeCase = { name: string; edits: MapEdits; comments?: string[]; code: string };
type ReadCase = { name: string; code: string; edits: MapEdits; comments: string[] };
type RefusedCase = { name: string; code: string; reason: string };
type ApplyCase = { name: string; key: string; edits: MapEdits; features: MapFeature[]; expected: MapFeature[] };

const shared = codeCases as unknown as { cases: CodeCase[]; read: ReadCase[]; refused: RefusedCase[] };
const applied = (applyCases as unknown as { cases: ApplyCase[] }).cases;

/** U+0085, U+2028 and U+2029, which Python's `splitlines` breaks a line on. */
const BREAKS = String.fromCharCode(0x85, 0x2028, 0x2029);

describe("mapEditsCode", () => {
  test.each(shared.cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(mapEditsCode(c.edits, c.comments)).toBe(c.code);
  });

  test("calls the sandbox's helper with the node's input", () => {
    expect(mapEditsCode({ remove: [], change: [] })).toContain(`\nreturn ${MAP_EDITS_HELPER}(\n    input_0,\n`);
  });

  test("writes the line breaks Python's splitlines knows as escapes", () => {
    const note = `a${BREAKS[1]}b${BREAKS[0]}c${BREAKS[2]}`;
    const code = mapEditsCode({ key: "osm_id", remove: [], change: [{ id: 1, values: { note } }] });
    expect(code).toContain('change={1: {"note": "a\\u2028b\\u0085c\\u2029"}},');
    expect(new RegExp(`[${BREAKS}]`).test(code)).toBe(false);
    expect(readMapEdits(code)).toEqual({ edits: { key: "osm_id", remove: [], change: [{ id: 1, values: { note } }] }, comments: mapEditsComment("osm_id") });
  });

  test("names a key with a line break on one comment line", () => {
    const code = mapEditsCode({ key: "a\nb", remove: [], change: [] });
    expect(code.split("\n").slice(0, 2)).toEqual(mapEditsComment("a b"));
    expect(code).toContain('    key="a\\nb",\n');
    expect(readMapEdits(code)).toEqual({ edits: { key: "a\nb", remove: [], change: [] }, comments: mapEditsComment("a b") });
  });

  test("writes no value that is not an id as one", () => {
    const code = mapEditsCode({ remove: [Number.NaN, 1], change: [{ id: Number.POSITIVE_INFINITY, values: { height: 1 } }] });
    expect(code).toContain("    remove=[1],\n    change={},\n");
  });
});

describe("readMapEdits", () => {
  test.each(shared.cases.map((c) => [c.name, c] as const))("reads back: %s", (_name, c) => {
    const read = readMapEdits(c.code);
    if ("problem" in read) throw new Error(read.problem);
    expect(read.edits).toEqual(c.edits);
    expect(mapEditsCode(read.edits, read.comments)).toBe(c.code);
  });

  test.each(shared.read.map((c) => [c.name, c] as const))("reads: %s", (_name, c) => {
    expect(readMapEdits(c.code)).toEqual({ edits: c.edits, comments: c.comments });
  });

  test.each(shared.refused.map((c) => [c.name, c] as const))("refuses: %s", (_name, c) => {
    expect(readMapEdits(c.code)).toEqual({ problem: expect.stringContaining(c.reason) });
  });

  test("reads blank code as a new node: no edits, and no comment lines of its own", () => {
    for (const code of ["", "  \n\n", null, undefined]) {
      expect(readMapEdits(code)).toStrictEqual({ edits: { remove: [], change: [] } });
    }
  });

  test("reads an id removed twice once, and an id with nothing to write as no change", () => {
    expect(readMapEdits('return curio_map_edits(input_0, key="osm_id", remove=[1, 1.0, "1"], change={2: {}})\n')).toEqual({
      edits: { key: "osm_id", remove: [1, "1"], change: [] },
      comments: [],
    });
  });

  test("keeps a comment line that names a reference, since the code below it reads none", () => {
    expect(readMapEdits("# from [!! selection towers !!]\nreturn curio_map_edits(input_0)\n")).toEqual({
      edits: { remove: [], change: [] },
      comments: ["# from [!! selection towers !!]"],
    });
  });
});

describe("changeFromField", () => {
  const original = { building_id: 34, height: 120, "building:levels": 35, osm_id: 1001 };

  test("writes the values that changed", () => {
    expect(changeFromField({ shown: original, original, edited: { ...original, height: 60 }, key: "building_id" })).toEqual({
      values: { height: 60 },
      written: { height: 60 },
    });
  });

  test("makes no change of a field left as it was", () => {
    expect(changeFromField({ shown: original, original, edited: { ...original }, key: "building_id" })).toEqual({ noChange: true });
  });

  test("writes a deleted key as null", () => {
    const { osm_id: _deleted, ...edited } = original;
    expect(changeFromField({ shown: original, original, edited, key: "building_id" })).toEqual({
      values: { osm_id: null },
      written: { osm_id: null },
    });
  });

  test("drops a value typed back to the input's, and with it an empty change", () => {
    const current = { height: 60 };
    const shown = { ...original, ...current };
    expect(changeFromField({ shown, original, edited: { ...shown, height: 120 }, key: "building_id", current })).toEqual({
      values: {},
      written: { height: 120 },
    });
    // A key the input lacks, added by an earlier Apply and then deleted: its null is the input's.
    const added = { note: "x" };
    expect(changeFromField({ shown: { ...original, ...added }, original, edited: original, key: "building_id", current: added })).toEqual({
      values: {},
      written: { note: null },
    });
  });

  test("keeps the values earlier Applies wrote", () => {
    const current = { height: 60 };
    const shown = { ...original, ...current };
    expect(changeFromField({ shown, original, edited: { ...shown, name: "Tower" }, key: "building_id", current })).toEqual({
      values: { height: 60, name: "Tower" },
      written: { name: "Tower" },
    });
  });

  test("never writes a derived value the field shows untouched", () => {
    // A part with only building:levels, drawn with the height withReadableHeights derives: shown and original hold it.
    const part = { building_id: 7, "building:levels": 3, height: 9.6 };
    expect(changeFromField({ shown: part, original: part, edited: { ...part, name: "Annex" }, key: "building_id" })).toEqual({
      values: { name: "Annex" },
      written: { name: "Annex" },
    });
  });

  test("refuses a change of the key's value, or of the geometry", () => {
    const refused = { problem: expect.stringContaining("building_id identifies the feature") };
    expect(changeFromField({ shown: original, original, edited: { ...original, building_id: 35 }, key: "building_id" })).toEqual(refused);
    const { building_id: _id, ...withoutKey } = original;
    expect(changeFromField({ shown: original, original, edited: withoutKey, key: "building_id" })).toEqual(refused);
    expect(changeFromField({ shown: original, original, edited: { ...original, geometry: null }, key: "building_id" })).toEqual({
      problem: expect.stringContaining("geometry"),
    });
  });

  test("refuses half of a character, which the node could not read back, and takes a whole one", () => {
    const half = `a${String.fromCharCode(0xd800)}`;
    expect(changeFromField({ shown: original, original, edited: { ...original, name: half }, key: "building_id" })).toEqual({
      problem: expect.stringContaining("half of a character"),
    });
    const whole = String.fromCodePoint(0x1f600);
    const change = changeFromField({ shown: original, original, edited: { ...original, name: whole }, key: "building_id" });
    expect(change).toEqual({ values: { name: whole }, written: { name: whole } });
    if (!("values" in change)) throw new Error("no change");
    expect(readMapEdits(mapEditsCode(withChange({ key: "building_id", remove: [], change: [] }, 34, change.values)))).toMatchObject({
      edits: { change: [{ id: 34, values: { name: whole } }] },
    });
  });

  test("refuses a field that is not one JSON object, and a node with no key", () => {
    for (const edited of [null, [original], "height", 60]) {
      expect(changeFromField({ shown: original, original, edited, key: "building_id" })).toEqual({ problem: expect.stringContaining("one JSON object") });
    }
    expect(changeFromField({ shown: original, original, edited: original, key: undefined })).toEqual({ problem: expect.stringContaining("Pick the column") });
  });

  test("makes no change of an Apply that leaves the change as it is", () => {
    // The height the change writes, and a null for a key the input lacks.
    const current = { height: 60 };
    const shown = { ...original, ...current };
    expect(changeFromField({ shown, original, edited: { ...shown, extra: null }, key: "building_id", current })).toEqual({ noChange: true });
  });

  test("compares nested values whatever the order of their keys", () => {
    const shown = { building_id: 1, tags: { a: 1, b: [1, 2] } };
    expect(changeFromField({ shown, original: shown, edited: { building_id: 1, tags: { b: [1, 2], a: 1 } }, key: "building_id" })).toEqual({ noChange: true });
    expect(changeFromField({ shown, original: shown, edited: { building_id: 1, tags: { a: 1, b: [2, 1] } }, key: "building_id" })).toEqual({
      values: { tags: { a: 1, b: [2, 1] } },
      written: { tags: { a: 1, b: [2, 1] } },
    });
  });
});

describe("the edits' helpers", () => {
  const edits: MapEdits = {
    key: "building_id",
    remove: [8],
    change: [{ id: 12, values: { height: 60 } }, { id: "12", values: { name: "B" } }],
  };

  test("withRemoved adds each id once, after the others, and drops its change", () => {
    expect(withRemoved(edits, [12, 8, 10, 10])).toEqual({
      key: "building_id",
      remove: [8, 12, 10],
      change: [{ id: "12", values: { name: "B" } }],
    });
    expect(edits.remove).toEqual([8]);
  });

  test("withPutBack puts back one id", () => {
    expect(withPutBack({ ...edits, remove: [8, 10, "8"] }, 8)).toEqual({ ...edits, remove: [10, "8"] });
  });

  test("withChange replaces an id's change in its place, adds a new one last, and drops an empty one", () => {
    expect(withChange(edits, 12, { height: 70 }).change).toEqual([{ id: 12, values: { height: 70 } }, { id: "12", values: { name: "B" } }]);
    expect(withChange(edits, 34, { height: 1 }).change.map((c) => c.id)).toEqual([12, "12", 34]);
    expect(withChange(edits, 12, {}).change).toEqual([{ id: "12", values: { name: "B" } }]);
    expect(withChange(edits, 34, {})).toEqual(edits);
  });

  test("compare ids as the sandbox does: 12 and 12.0 are one id, the text 12 is another", () => {
    expect([sameId(12, 12.0), sameId(12, "12"), sameId("w1", "w1")]).toEqual([true, false, true]);
    expect([changeFor(edits, 12), changeFor(edits, "12"), changeFor(edits, 13)]).toEqual([{ height: 60 }, { name: "B" }, undefined]);
    expect([isRemoved(edits, 8), isRemoved(edits, "8")]).toEqual([true, false]);
    expect([1, "a", 1.5, Number.NaN, Number.POSITIVE_INFINITY, true, null, undefined, {}].map(isFeatureId)).toEqual([
      true, true, true, false, false, false, false, false, false,
    ]);
  });
});

describe("the labels of the node's Provenance entries", () => {
  test("name what changed and the id it changed", () => {
    expect(removeLabel("building_id", [12])).toBe("remove building_id 12");
    expect(putBackLabel("building_id", 12)).toBe("put back building_id 12");
    expect(changeLabel("building_id", 34, { height: 60 })).toBe("height 60 on building_id 34");
    expect(changeLabel("building_id", 34, { height: 60, name: null })).toBe("height 60, name cleared on building_id 34");
    expect(changeLabel("osm_id", "w7", { name: "O'Hare" })).toBe(`name "O'Hare" on osm_id w7`);
  });

  test("cut long values and long lists short", () => {
    expect(changeLabel("building_id", 34, { note: "x".repeat(100) })).toBe(`note "${"x".repeat(22)}… on building_id 34`);
    expect(removeLabel("building_id", [1, 2, 3, 4, 5, 6, 7])).toBe("remove building_id 1, 2, 3, 4, 5 and 2 more");
  });
});

describe("applyMapEdits", () => {
  test.each(applied.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const before = JSON.parse(JSON.stringify(c.features));
    expect(applyMapEdits(c.features, { ...c.edits, key: c.key })).toEqual(c.expected);
    expect(c.features).toEqual(before);
  });

  test("hands on the features no edit names as they are, and applies nothing without a key", () => {
    const part = (building_id: number, height: number): MapFeature => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [building_id, 0] },
      properties: { building_id, height },
    });
    const features = [part(1, 10), part(2, 20)];
    const out = applyMapEdits(features, { key: "building_id", remove: [], change: [{ id: 1, values: { height: 0 } }] });
    expect(out[0]).not.toBe(features[0]);
    expect(out[1]).toBe(features[1]);
    expect(features[0].properties).toEqual({ building_id: 1, height: 10 });
    const keyless = applyMapEdits(features, { remove: [1], change: [{ id: 2, values: { height: 0 } }] });
    expect(keyless).toEqual(features);
    expect(keyless[0]).toBe(features[0]);
  });
});
