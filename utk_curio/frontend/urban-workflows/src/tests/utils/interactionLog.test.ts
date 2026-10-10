/**
 * The Interaction node's edit log: its expressions, the log applied for the
 * map's preview, and the entries it keeps. `applyEdits.cases.json` is shared
 * with `utk_curio/sandbox/tests/test_feature_edits.py`, so the preview and a
 * run apply an edit the same way.
 */
import shared from "../../utils/editFeatures/applyEdits.cases.json";
import { evaluate, exprProblem, parseExpr } from "../../utils/editFeatures/editExpr";
import { applyEdits } from "../../utils/editFeatures/applyEdits";
import {
  describeEdit,
  normalizeEdit,
  normalizeEditFeatures,
  withEditEnabled,
  withNudge,
  type EditFeaturesSettings,
} from "../../utils/editFeatures/editFeatures";

describe("expressions", () => {
  test.each(shared.expressions.map((c) => [c.expr, c] as const))("%s", (_name, c) => {
    expect(evaluate(parseExpr(c.expr), c.row as Record<string, unknown>)).toEqual(c.value);
  });

  test.each(shared.refusals)("refuses %p", (text) => {
    expect(exprProblem(text)).not.toBeNull();
  });
});

describe("the log applied for the preview", () => {
  test.each(shared.edits.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const fc = { type: "FeatureCollection", features: c.features.map((properties, i) => ({ type: "Feature", geometry: { type: "Point", coordinates: [i, 0] }, properties })) };
    const settings = normalizeEditFeatures({ key: c.key, edits: c.edits });
    expect(settings?.edits).toHaveLength(c.edits.length);
    const { fc: out, counts, problem } = applyEdits(fc, settings, c.key);
    expect(problem).toBeNull();
    expect(out.features.map((f: any) => f.properties)).toEqual(c.expected);
    expect(counts).toEqual(c.counts);
  });

  test("an untouched feature stays the same object", () => {
    const fc = { features: [{ properties: { id: 1 } }, { properties: { id: 2, h: 1 } }] };
    const { fc: out } = applyEdits(fc, { key: "id", edits: [{ op: "offset", ids: [2], column: "h", value: 1 }] }, "id");
    expect(out.features[0]).toBe(fc.features[0]);
    expect(out.features[1]).not.toBe(fc.features[1]);
  });

  test("a condition that is not one is a problem, and the input is drawn", () => {
    const fc = { features: [{ properties: { id: 1 } }] };
    const { fc: out, problem } = applyEdits(fc, { key: "id", edits: [{ op: "remove", where: "id >" }] }, "id");
    expect(problem).toMatch(/ends too soon|expected/);
    expect(out).toBe(fc);
  });
});

describe("log entries", () => {
  test("an entry names its features by ids or by a condition, not both", () => {
    expect(normalizeEdit({ op: "remove", ids: [1], where: "a > 1" })).toBeNull();
    expect(normalizeEdit({ op: "remove" })).toBeNull();
    expect(normalizeEdit({ op: "remove", where: " a > 1 " })).toEqual({ op: "remove", where: "a > 1" });
  });

  test("a scale or an offset takes a number, an expression a text", () => {
    expect(normalizeEdit({ op: "scale", ids: [1], column: "h", value: "2" })).toBeNull();
    expect(normalizeEdit({ op: "expr", ids: [1], column: "h", value: 2 })).toBeNull();
    expect(normalizeEdit({ op: "expr", ids: [1], column: "h", value: "levels * 3" })).toEqual({ op: "expr", ids: [1], column: "h", value: "levels * 3" });
  });

  test("an entry keeps its label and its switch", () => {
    expect(normalizeEdit({ op: "remove", ids: [1], label: " Tower ", enabled: false })).toEqual({ op: "remove", ids: [1], label: "Tower", enabled: false });
    expect(normalizeEdit({ op: "remove", ids: [1], enabled: true })).toEqual({ op: "remove", ids: [1] });
  });

  test("switching an entry off and on", () => {
    const settings: EditFeaturesSettings = { key: "id", edits: [{ op: "remove", ids: [1] }] };
    const off = withEditEnabled(settings, 0, false);
    expect(off?.edits?.[0].enabled).toBe(false);
    expect(withEditEnabled(off, 0, true)?.edits?.[0]).toEqual({ op: "remove", ids: [1] });
  });

  test("repeated nudges fold into one entry, and a nudge back to nothing drops it", () => {
    let settings: EditFeaturesSettings | undefined = { key: "id" };
    const up = { op: "offset" as const, ids: [7], column: "height", value: 3 };
    settings = withNudge(settings, up);
    settings = withNudge(settings, up);
    expect(settings.edits).toEqual([{ op: "offset", ids: [7], column: "height", value: 6 }]);
    settings = withNudge(settings, { ...up, ids: [8] });
    expect(settings.edits).toHaveLength(2);
    settings = withNudge(settings, { ...up, ids: [8], value: -3 });
    expect(settings.edits).toEqual([{ op: "offset", ids: [7], column: "height", value: 6 }]);
  });

  test("each entry reads as a sentence", () => {
    expect(describeEdit({ op: "scale", where: "height > 100", column: "height", value: 0.5 }, "building_id")).toBe("Scale height ×0.5 on where height > 100");
    expect(describeEdit({ op: "offset", ids: [3], column: "height", value: -6 }, "building_id")).toBe("Lower height by 6 on building_id 3");
    expect(describeEdit({ op: "remove", ids: [1, 2], label: "Towers" }, "building_id")).toBe("Towers: Remove building_id 1, 2");
    expect(describeEdit({ op: "expr", ids: [1], column: "height", value: "levels * 3.2" }, "osm_id")).toBe("Set height = levels * 3.2 on osm_id 1");
  });
});
