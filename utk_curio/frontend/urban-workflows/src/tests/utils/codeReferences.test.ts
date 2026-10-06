/**
 * How a node's references become code (#662): `[!! name !!]` its widgets'
 * values, `[!! input 1 !!]` its inputs, `[!! input 1.height !!]` their columns.
 *
 * The cases live in `utils/references/codeReferences.cases.json`, which
 * `utk_curio/backend/tests/test_execution/test_code_references.py` reads too:
 * the headless runner must write the same code the browser does.
 */
import cases from "../../utils/references/codeReferences.cases.json";
import {
  describeEmptyInputs,
  describeReferenceProblems,
  findReferences,
  isReferenceableColumn,
  parseReference,
  renumberInputReferences,
  resolveReferences,
  widgetLiteral,
  type CodeLanguage,
  type InputScope,
} from "../../utils/references/codeReferences";
import { normalizeWidgets } from "../../utils/widgets/widgetModel";
import { normalizeShared } from "../../utils/references/sharedParameters";
import type { SelectionTag } from "../../utils/references/selectionTags";

type Case = {
  name: string;
  language: CodeLanguage;
  code: string;
  widgets: unknown[];
  inputs?: InputScope[];
  shared?: unknown[];
  selections?: unknown[];
  expected: string;
  problems?: string[];
};

describe("the shared reference cases", () => {
  test.each((cases.cases as Case[]).map((c) => [c.name, c]))("%s", (_name, c) => {
    const result = resolveReferences(
      c.code,
      {
        widgets: normalizeWidgets(c.widgets),
        inputs: c.inputs ?? [],
        shared: normalizeShared(c.shared ?? []),
        // The table's tags are well formed, as the editor's scope holds them.
        selections: (c.selections ?? []) as SelectionTag[],
      },
      c.language,
    );
    expect(result.code).toBe(c.expected);
    expect(result.problems.map((p) => p.message)).toEqual(c.problems ?? []);
  });

  test("the table has selection references that resolve in every language", () => {
    for (const language of ["python", "javascript", "json"]) {
      const resolved = (cases.cases as Case[]).filter(
        (c) => c.language === language && c.code.includes("[!! selection ") && !c.problems,
      );
      expect(resolved.length).toBeGreaterThan(0);
    }
  });

  test("the table covers every language", () => {
    const languages = new Set((cases.cases as Case[]).map((c) => c.language));
    expect([...languages].sort()).toEqual(["javascript", "json", "python"]);
  });

  test("the table has input references in every language", () => {
    for (const language of ["python", "javascript", "json"]) {
      const codes = (cases.cases as Case[]).filter((c) => c.language === language).map((c) => c.code).join(" ");
      expect(codes).toMatch(/\[!! input \d/);
    }
  });

  test("the table has layer references that resolve in every language, code as well as specs", () => {
    for (const language of ["python", "javascript", "json"]) {
      const resolved = (cases.cases as Case[]).filter(
        (c) => c.language === language && /\[!! input \d+:[^.\s]+ !!\]/.test(c.code) && !c.problems,
      );
      expect([language, resolved.length > 0]).toEqual([language, true]);
    }
  });
});

describe("a layer chip in code", () => {
  const layered: InputScope[] = [{ slot: 0, layers: [{ name: "table_osm_roads" }, { name: "table_osm_buildings" }] }];
  const scope = (inputs: InputScope[]) => ({ widgets: [], inputs, shared: [] });

  test("is the call that picks the layer, in Python and JavaScript alike", () => {
    for (const language of ["python", "javascript"] as CodeLanguage[]) {
      const result = resolveReferences("x = [!! input 0:table_osm_roads !!]", scope(layered), language);
      expect(result).toEqual({ code: 'x = curio_layer(arg, "table_osm_roads", 0)', problems: [] });
    }
  });

  test("a layer the input does not have names the ones it has", () => {
    const result = resolveReferences("x = [!! input 0:table_osm_water !!]", scope(layered), "python");
    expect(describeReferenceProblems(result.problems)).toBe(
      "[!! input 0:table_osm_water !!]: input 0 has no layer table_osm_water. "
        + "Its layers are table_osm_roads, table_osm_buildings.",
    );
  });

  test("closing up circles renumbers a layer chip and keeps its layer", () => {
    const code = "a = [!! input 1:table_osm_roads !!]";
    expect(renumberInputReferences(code, 0)).toBe("a = [!! input 0:table_osm_roads !!]");
  });
});

describe("references", () => {
  test("found with their offsets and trimmed names", () => {
    const code = "a = [!!  x !!] + [!! y!!]";
    expect(findReferences(code)).toEqual([
      { start: 4, end: 14, inner: "x" },
      { start: 17, end: 25, inner: "y" },
    ]);
  });

  test("problems read as one message, a line each", () => {
    const { problems } = resolveReferences("[!! a !!] [!! b$X$1 !!]", { widgets: [], inputs: [], shared: [] }, "python");
    expect(describeReferenceProblems(problems).split("\n")).toHaveLength(2);
  });

  test("an input, a column and a widget are told apart", () => {
    expect(parseReference("input 2")).toEqual({ kind: "input", slot: 2 });
    expect(parseReference("input 2.pop.2020")).toEqual({ kind: "input", slot: 2, column: "pop.2020" });
    expect(parseReference("input ?")).toEqual({ kind: "input", slot: null });
    expect(parseReference("input")).toEqual({ kind: "widget", name: "input" });
    expect(parseReference("input_2")).toEqual({ kind: "widget", name: "input_2" });
  });

  test("a selection tag is told apart from a widget named selection", () => {
    expect(parseReference("selection picked")).toEqual({ kind: "selection", name: "picked" });
    expect(parseReference("selection")).toEqual({ kind: "widget", name: "selection" });
    expect(parseReference("selection_2")).toEqual({ kind: "widget", name: "selection_2" });
    expect(parseReference("@selection")).toEqual({ kind: "shared", name: "selection" });
  });

  test("a column name that would not read back is not offered", () => {
    expect(isReferenceableColumn("height")).toBe(true);
    expect(isReferenceableColumn("pop 2020")).toBe(true);
    expect(isReferenceableColumn(" padded")).toBe(false);
    expect(isReferenceableColumn("a!!]b")).toBe(false);
    expect(isReferenceableColumn("two\nlines")).toBe(false);
    expect(isReferenceableColumn("")).toBe(false);
  });

  test("an empty input is named, with the node that feeds it", () => {
    const message = describeEmptyInputs([1], [{ slot: 0 }, { slot: 1, label: "Parcels" }]);
    expect(message).toBe("Input 1 (from Parcels) has no value yet. Run the node that feeds it.");
  });
});

describe("closing up circles", () => {
  test("later inputs count one less, the deleted one reports itself", () => {
    const code = "a = [!! input 0 !!]\nb = [!! input 1.area !!]\nc = [!!input 2!!]\nw = [!! factor !!]";
    expect(renumberInputReferences(code, 1)).toBe(
      "a = [!! input 0 !!]\nb = [!! input ?.area !!]\nc = [!! input 1 !!]\nw = [!! factor !!]",
    );
  });

  test("code without input references is returned as it is", () => {
    const code = "x = [!! factor !!] # input 3";
    expect(renumberInputReferences(code, 0)).toBe(code);
  });

  test("deleting two circles, the lower first, keeps each chip on its input", () => {
    const code = "[!! input 0 !!] [!! input 1 !!] [!! input 2 !!] [!! input 3 !!]";
    const once = renumberInputReferences(code, 2);
    expect(renumberInputReferences(once, 1)).toBe("[!! input 0 !!] [!! input ? !!] [!! input ? !!] [!! input 1 !!]");
  });

  test("after closing up, the chips resolve to the inputs they named", () => {
    // Inputs 0, 1 and 2 feed the node; input 1 is deleted, so input 2 is now
    // input 1 and is arg[1] of the two that remain.
    const code = renumberInputReferences("return [!! input 2 !!]", 1);
    const { code: resolved } = resolveReferences(
      code,
      { widgets: [], inputs: [{ slot: 0 }, { slot: 1 }], shared: [] },
      "python",
    );
    expect(resolved).toBe("return arg[1]");
  });
});

describe("literals", () => {
  test("Python spells booleans and nothing its own way", () => {
    expect(widgetLiteral(true, "python")).toBe("True");
    expect(widgetLiteral(null, "python")).toBe("None");
    expect(widgetLiteral(false, "json")).toBe("false");
    expect(widgetLiteral(null, "javascript")).toBe("null");
  });

  test("a number that is not finite is written as nothing", () => {
    expect(widgetLiteral(NaN, "python")).toBe("None");
    expect(widgetLiteral(Infinity, "json")).toBe("null");
  });
});
