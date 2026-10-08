/**
 * Which view a Compare Scenarios node (#662) is in, Chart or Difference, and
 * the code it writes for it.
 *
 * Without the user's choice the node picks Difference for exactly two rasters
 * or two layers and Chart otherwise, by the values its circles hold, and keeps
 * the view its code was written for until every input holds one.
 * `compareDifference.cases.json` holds the Difference code for a few sets of
 * inputs; `test_compare_difference_node.py` resolves the same code as a run on
 * the server does and runs it through the sandbox's difference step.
 */
import cases from "../../utils/compare/compareDifference.cases.json";
import {
  DIFFERENCE_HELPER,
  absoluteOfCode,
  compareCode,
  differenceCode,
  keyOfCode,
  modeOfCode,
  stackCode,
} from "../../utils/compare/compareCode";
import { automaticMode, inputKind, inputKinds, resolveMode, wantedMode, type InputKind } from "../../utils/compare/compareMode";
import { normalizeCompareSettings, type CompareInputLabel } from "../../utils/compare/compareSettings";
import { resolveReferences } from "../../utils/references/codeReferences";

type CodeCase = { name: string; key?: string; absolute?: boolean; inputs: { slot: number; label: CompareInputLabel }[]; code: string };

const BASE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f" };
const TALL = { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" };
const TWO = [
  { slot: 0, label: BASE },
  { slot: 1, label: TALL },
];

describe("an input's kind", () => {
  test("is read from the value its circle holds: a raster, a layer, a table, or something else", () => {
    expect(inputKind({ path: "a", dataType: "raster" })).toBe("raster");
    // A raster an Autark node hands on, its envelope itself.
    expect(inputKind({ dataType: "raster", data: { type: "FeatureCollection" } })).toBe("raster");
    expect(inputKind({ path: "a", dataType: "geodataframe" })).toBe("layer");
    expect(inputKind({ path: "a", dataType: "dataframe" })).toBe("table");
    expect(inputKind({ path: "a", dataType: "dict" })).toBe("other");
    expect(inputKind(42)).toBe("other");
  });

  test("is not known while the circle holds nothing", () => {
    expect(inputKind(undefined)).toBeNull();
    expect(inputKind(null)).toBeNull();
    expect(inputKind("")).toBeNull();
  });

  test("of each wired circle, in circle order", () => {
    const slots = [{ path: "a", dataType: "raster" }, undefined, { path: "c", dataType: "geodataframe" }];
    expect(inputKinds(slots, [0, 2])).toEqual(["raster", "layer"]);
    expect(inputKinds(slots, [1])).toEqual([null]);
    expect(inputKinds(undefined, [0, 1])).toEqual([null, null]);
  });
});

describe("the view the node picks", () => {
  test.each<[InputKind[], string]>([
    [["raster", "raster"], "difference"],
    [["layer", "layer"], "difference"],
    [["table", "table"], "chart"],
    [["raster", "layer"], "chart"],
    [["layer", "layer", "layer"], "chart"],
    [["layer"], "chart"],
    [["other", "other"], "chart"],
  ])("%j: %s", (kinds, mode) => {
    expect(automaticMode(kinds)).toBe(mode);
  });

  test("is not picked while an input has not run, or while it has none", () => {
    expect(automaticMode(["raster", null])).toBeNull();
    expect(automaticMode([])).toBeNull();
  });

  test("gives way to the user's choice", () => {
    expect(wantedMode({ mode: "chart" }, ["raster", "raster"])).toBe("chart");
    expect(wantedMode({ mode: "difference" }, ["table", "table"])).toBe("difference");
    expect(wantedMode(undefined, ["raster", "raster"])).toBe("difference");
    expect(wantedMode({ inputs: [BASE] }, [null])).toBeNull();
  });

  test("until the inputs are known, is the view the node's code was written for", () => {
    expect(resolveMode(undefined, [null, null], differenceCode(TWO))).toEqual({ mode: "difference", chosen: false });
    expect(resolveMode(undefined, [null, null], stackCode(TWO))).toEqual({ mode: "chart", chosen: false });
    // Code written by hand, or none: Chart.
    expect(resolveMode(undefined, [], "return input")).toEqual({ mode: "chart", chosen: false });
    expect(resolveMode(undefined, [], undefined)).toEqual({ mode: "chart", chosen: false });
    expect(resolveMode(undefined, ["layer", "layer"], stackCode(TWO))).toEqual({ mode: "difference", chosen: false });
    expect(resolveMode({ mode: "difference" }, ["table", "table"], stackCode(TWO))).toEqual({ mode: "difference", chosen: true });
  });
});

describe("the code it writes in Difference", () => {
  test("the code says when it gives each difference's size, and the key still comes last", () => {
    const code = differenceCode(TWO, "osm_id", undefined, true);
    expect(code).toContain("], absolute=True, key=\"osm_id\")");
    expect(absoluteOfCode(code)).toBe(true);
    expect(keyOfCode(code)).toBe("osm_id");
    expect(absoluteOfCode(differenceCode(TWO))).toBe(false);
  });

  test.each((cases.cases as CodeCase[]).map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(differenceCode(c.inputs, c.key, undefined, c.absolute)).toBe(c.code);
  });

  test("calls the sandbox's difference step", () => {
    expect(differenceCode([])).toContain(`return ${DIFFERENCE_HELPER}([])`);
  });

  test("its chips read the inputs as any Python node's do: input_0 the reference, input_1 the comparison", () => {
    const [two] = cases.cases as CodeCase[];
    const scope = { widgets: [], shared: [], inputs: [{ slot: 0 }, { slot: 1 }] };
    const resolved = resolveReferences(two.code, scope, "python");
    expect(resolved.problems).toEqual([]);
    expect(resolved.code).toContain('("s-base", "Baseline", input_0),');
    expect(resolved.code).toContain('("s-tall", "Twice as tall", input_1),');
  });

  test("is the code of the view, keyed by the view", () => {
    expect(compareCode("chart", TWO, { key: "segment" })).toBe(stackCode(TWO));
    expect(compareCode("difference", TWO, { key: "segment" })).toBe(differenceCode(TWO, "segment"));
    expect(compareCode("difference", TWO)).toBe(differenceCode(TWO));
  });

  test("says which view and which key it was written for", () => {
    expect(modeOfCode(differenceCode(TWO, "segment"))).toBe("difference");
    expect(modeOfCode(stackCode(TWO))).toBe("chart");
    expect(modeOfCode("return input")).toBeNull();
    expect(keyOfCode(differenceCode(TWO, 'the "id"'))).toBe('the "id"');
    expect(keyOfCode(differenceCode(TWO))).toBeUndefined();
    expect(keyOfCode(stackCode(TWO))).toBeUndefined();
  });
});

describe("the node's settings", () => {
  test("keep a chosen view and what Difference joins on and maps, and nothing else", () => {
    expect(
      normalizeCompareSettings({
        inputs: [BASE, TALL],
        mode: "difference",
        difference: { key: "osm_id", value: "sunlight", band: 1 },
      }),
    ).toEqual({ inputs: [BASE, TALL], mode: "difference", difference: { key: "osm_id", value: "sunlight" } });
    expect(normalizeCompareSettings({ mode: "chart" })).toEqual({ mode: "chart" });
  });

  test("drop a view the node does not have and an empty key, so nothing is written", () => {
    expect(normalizeCompareSettings({ mode: "map", difference: { key: "", value: " " } })).toBeUndefined();
    expect(normalizeCompareSettings({ difference: "osm_id" })).toBeUndefined();
  });
});
