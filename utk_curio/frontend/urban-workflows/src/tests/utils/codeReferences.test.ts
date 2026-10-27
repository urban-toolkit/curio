/**
 * How a node's references become code (#662): `[!! name !!]` its widgets'
 * values, `[!! input_1 !!]` its inputs, `[!! input_1.height !!]` their columns.
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
  withChipPlaceholders,
  type CodeLanguage,
  type InputScope,
} from "../../utils/references/codeReferences";
import { normalizeWidgets } from "../../utils/widgets/widgetModel";
import type { SelectionTag } from "../../utils/references/selectionTags";

type Case = {
  name: string;
  language: CodeLanguage;
  /** A JSON document's grammar, such as vega-lite. */
  grammar?: string;
  code: string;
  widgets: unknown[];
  inputs?: InputScope[];
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
        // The table's tags are well formed, as the editor's scope holds them.
        selections: (c.selections ?? []) as SelectionTag[],
      },
      c.language,
      c.grammar,
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

  test("the table refuses a name that starts with @ in every language: it names no widget", () => {
    for (const language of ["python", "javascript", "json"]) {
      const refused = (cases.cases as Case[]).filter(
        (c) =>
          c.language === language &&
          c.code.includes("[!! @") &&
          (c.problems ?? []).some((p) => p.startsWith("[!! @") && p.includes("does not name a widget.")),
      );
      expect([language, refused.length > 0]).toEqual([language, true]);
    }
    expect(parseReference("@season")).toEqual({ kind: "widget", name: "@season" });
  });

  test("the table has input references in every language", () => {
    for (const language of ["python", "javascript", "json"]) {
      const codes = (cases.cases as Case[]).filter((c) => c.language === language).map((c) => c.code).join(" ");
      expect(codes).toMatch(/\[!! input_\d/);
    }
  });

  test("the table has layer references that resolve in every language, code as well as specs", () => {
    for (const language of ["python", "javascript", "json"]) {
      const resolved = (cases.cases as Case[]).filter(
        (c) => c.language === language && /\[!! input_\d+:[^.\s]+ !!\]/.test(c.code) && !c.problems,
      );
      expect([language, resolved.length > 0]).toEqual([language, true]);
    }
  });
});

describe("a layer chip in code", () => {
  const layered: InputScope[] = [{ slot: 0, layers: [{ name: "table_osm_roads" }, { name: "table_osm_buildings" }] }];
  const scope = (inputs: InputScope[]) => ({ widgets: [], inputs });

  test("is the call that picks the layer, in Python and JavaScript alike", () => {
    for (const language of ["python", "javascript"] as CodeLanguage[]) {
      const result = resolveReferences("x = [!! input_0:table_osm_roads !!]", scope(layered), language);
      expect(result).toEqual({ code: 'x = curio_layer(input_0, "table_osm_roads", 0)', problems: [] });
    }
  });

  test("a layer the input does not have names the ones it has", () => {
    const result = resolveReferences("x = [!! input_0:table_osm_water !!]", scope(layered), "python");
    expect(describeReferenceProblems(result.problems)).toBe(
      "[!! input_0:table_osm_water !!]: input_0 has no layer table_osm_water. "
        + "Its layers are table_osm_roads, table_osm_buildings.",
    );
  });

  test("closing up circles renumbers a layer chip and keeps its layer", () => {
    const code = "a = [!! input_1:table_osm_roads !!]";
    expect(renumberInputReferences(code, 0)).toBe("a = [!! input_0:table_osm_roads !!]");
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
    const { problems } = resolveReferences("[!! a !!] [!! b$X$1 !!]", { widgets: [], inputs: [] }, "python");
    expect(describeReferenceProblems(problems).split("\n")).toHaveLength(2);
  });

  test("an input, a column and a widget are told apart", () => {
    expect(parseReference("input_2")).toEqual({ kind: "input", slot: 2 });
    expect(parseReference("input_2.pop.2020")).toEqual({ kind: "input", slot: 2, column: "pop.2020" });
    expect(parseReference("input_?")).toEqual({ kind: "input", slot: null });
    expect(parseReference("input")).toEqual({ kind: "widget", name: "input" });
    expect(parseReference("input_area")).toEqual({ kind: "widget", name: "input_area" });
  });

  test("a selection tag is told apart from a widget named selection", () => {
    expect(parseReference("selection picked")).toEqual({ kind: "selection", name: "picked" });
    expect(parseReference("selection")).toEqual({ kind: "widget", name: "selection" });
    expect(parseReference("selection_2")).toEqual({ kind: "widget", name: "selection_2" });
    expect(parseReference("@selection")).toEqual({ kind: "widget", name: "@selection" });
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
    expect(message).toBe("input_1 (from Parcels) has no value yet. Run the node that feeds it.");
  });
});

describe("closing up circles", () => {
  test("later inputs count one less, the deleted one reports itself", () => {
    const code = "a = [!! input_0 !!]\nb = [!! input_1.area !!]\nc = [!!input_2!!]\nw = [!! factor !!]";
    expect(renumberInputReferences(code, 1)).toBe(
      "a = [!! input_0 !!]\nb = [!! input_?.area !!]\nc = [!! input_1 !!]\nw = [!! factor !!]",
    );
  });

  test("code without input references is returned as it is", () => {
    const code = "x = [!! factor !!] # input_3";
    expect(renumberInputReferences(code, 0)).toBe(code);
  });

  test("deleting two circles, the lower first, keeps each chip on its input", () => {
    const code = "[!! input_0 !!] [!! input_1 !!] [!! input_2 !!] [!! input_3 !!]";
    const once = renumberInputReferences(code, 2);
    expect(renumberInputReferences(once, 1)).toBe("[!! input_0 !!] [!! input_? !!] [!! input_? !!] [!! input_1 !!]");
  });

  test("after closing up, the chips resolve to the inputs they named", () => {
    // Inputs 0, 1 and 2 feed the node; input_1 is deleted, so input_2 is now
    // input_1, the second of the two that remain.
    const code = renumberInputReferences("return [!! input_2 !!]", 1);
    const { code: resolved } = resolveReferences(
      code,
      { widgets: [], inputs: [{ slot: 0 }, { slot: 1 }] },
      "python",
    );
    expect(resolved).toBe("return input_1");
  });
});

describe("inputs named input_k", () => {
  test("a chip names its circle as the code reads it", () => {
    expect(parseReference("input_2")).toEqual({ kind: "input", slot: 2 });
    expect(parseReference("input_2.pop.2020")).toEqual({ kind: "input", slot: 2, column: "pop.2020" });
    expect(parseReference("input_0:roads.lanes")).toEqual({ kind: "input", slot: 0, layer: "roads", column: "lanes" });
    expect(parseReference("input_?")).toEqual({ kind: "input", slot: null });
  });

  test("a chip spelled the old way is refused, naming its new spelling", () => {
    const { code, problems } = resolveReferences(
      "x = [!! input 0 !!] + [!! input 1:roads.lanes !!]",
      { widgets: [], inputs: [{ slot: 0 }, { slot: 1 }] },
      "python",
    );
    expect(code).toBe("x = [!! input 0 !!] + [!! input 1:roads.lanes !!]");
    expect(problems.map((p) => p.message)).toEqual([
      "[!! input 0 !!] names an input the old way, which Curio no longer reads. Write [!! input_0 !!]: "
        + "each input circle is its own variable, input_0, input_1, and so on.",
      "[!! input 1:roads.lanes !!] names an input the old way, which Curio no longer reads. Write [!! input_1:roads.lanes !!]: "
        + "each input circle is its own variable, input_0, input_1, and so on.",
    ]);
  });

  test("closing up circles renumbers chips and typed names alike, and leaves strings, comments and other names", () => {
    const code = "a = input_0\nb = [!! input_1.area !!] + input_1\nc = [!! input_2 !!] + input_2  # input_2\n"
      + "s = 'input_2'\nx = obj.input_2 + my_input_2 + input_2x";
    expect(renumberInputReferences(code, 1)).toBe(
      "a = input_0\nb = [!! input_?.area !!] + [!! input_? !!]\nc = [!! input_1 !!] + input_1  # input_2\n"
        + "s = 'input_2'\nx = obj.input_2 + my_input_2 + input_2x",
    );
  });

  test("after closing up, the chips and names read the inputs they named", () => {
    // Inputs 0, 1 and 2 feed the node; input_1 is deleted, so input_2 is now
    // input_1, and the code reads it as input_1.
    const code = renumberInputReferences("return [!! input_2 !!], input_2", 1);
    const { code: resolved } = resolveReferences(
      code,
      { widgets: [], inputs: [{ slot: 0 }, { slot: 1 }] },
      "python",
    );
    expect(resolved).toBe("return input_1, input_1");
  });

  test("an empty input is named as the code reads it, with the node that feeds it", () => {
    const message = describeEmptyInputs([1], [{ slot: 0 }, { slot: 1, label: "Parcels" }]);
    expect(message).toBe("input_1 (from Parcels) has no value yet. Run the node that feeds it.");
  });
});

describe("closing up circles, with names inside f-strings", () => {
  test("a name inside an f-string's braces follows its circle, and the f-string's text does not", () => {
    const code = 'msg = f"input_2 is {input_2}, not {input_1}"';
    expect(renumberInputReferences(code, 1)).toBe('msg = f"input_2 is {input_1}, not {[!! input_? !!]}"');
  });

  test("single and triple quotes, and every f-string prefix", () => {
    const code = [
      "a = f'{input_2}'",
      'b = f"""total {input_2}"""',
      "c = f'''{input_2} of\n{input_3}'''",
      String.raw`d = rf"{input_2}\d+"`,
      "e = fr'{input_2}'",
      'g = Rf"{input_2}"',
      'h = F"{input_2}"',
    ].join("\n");
    expect(renumberInputReferences(code, 1)).toBe([
      "a = f'{input_1}'",
      'b = f"""total {input_1}"""',
      "c = f'''{input_1} of\n{input_2}'''",
      String.raw`d = rf"{input_1}\d+"`,
      "e = fr'{input_1}'",
      'g = Rf"{input_1}"',
      'h = F"{input_1}"',
    ].join("\n"));
  });

  test("names in nested format specs, and in strings inside the braces' expression", () => {
    const code = [
      'a = f"{input_2:>{input_3}}"',
      'b = f"{value:{input_2}.{input_3}f}"',
      `c = f"{input_2['name']} and {input_3["x"]!r:>10}"`,
      `d = f"{len(input_2)} rows, {d['input_2']}"`,
    ].join("\n");
    expect(renumberInputReferences(code, 1)).toBe([
      'a = f"{input_1:>{input_2}}"',
      'b = f"{value:{input_1}.{input_2}f}"',
      `c = f"{input_1['name']} and {input_2["x"]!r:>10}"`,
      `d = f"{len(input_1)} rows, {d['input_2']}"`,
    ].join("\n"));
  });

  test("plain strings, an f-string's escaped braces and comments keep the name as written", () => {
    const code = [
      's = "input_2"',
      "t = 'input_2'",
      'u = r"input_2"',
      'v = b"input_2"',
      'w = """input_2"""',
      'x = f"{{input_2}}"',
      'y = f"{{input_2}} {input_2}"',
      '# f"{input_2}"',
    ].join("\n");
    expect(renumberInputReferences(code, 1)).toBe([
      's = "input_2"',
      "t = 'input_2'",
      'u = r"input_2"',
      'v = b"input_2"',
      'w = """input_2"""',
      'x = f"{{input_2}}"',
      'y = f"{{input_2}} {input_1}"',
      '# f"{input_2}"',
    ].join("\n"));
  });

  test("a JavaScript template literal's ${...} follows its circle, and its text does not", () => {
    const code = "const s = `input_2 has ${input_2.length} rows, ${`${input_3}`}`;\nconst t = 'input_2';";
    expect(renumberInputReferences(code, 1, "javascript")).toBe(
      "const s = `input_2 has ${input_1.length} rows, ${`${input_2}`}`;\nconst t = 'input_2';",
    );
  });
});

describe("scenario chips, the dataset inputs and its fields", () => {
  test("the table has each scenario chip, the dataset inputs and a field of it resolving in a spec", () => {
    const resolving = (cases.cases as Case[]).filter((c) => c.language === "json" && !c.problems).map((c) => c.code).join(" ");
    for (const chip of ["scenario colors", "scenario text_colors", "scenario order", "scenario input_1", "inputs", "inputs.scenario_name"]) {
      expect([chip, resolving.includes(`[!! ${chip} !!]`)]).toEqual([chip, true]);
    }
  });

  test("are told apart from a widget, whose name has no space and no dot", () => {
    expect(parseReference("scenario colors")).toEqual({ kind: "scenario", chip: "colors" });
    expect(parseReference("scenario text_colors")).toEqual({ kind: "scenario", chip: "text_colors" });
    expect(parseReference("scenario order")).toEqual({ kind: "scenario", chip: "order" });
    expect(parseReference("scenario input_2")).toEqual({ kind: "scenario", chip: "input", slot: 2 });
    expect(parseReference("scenario input_?")).toEqual({ kind: "scenario", chip: "input", slot: null });
    expect(parseReference("scenario colours")).toEqual({ kind: "scenario", chip: null });
    expect(parseReference("inputs.scenario_name")).toEqual({ kind: "stacked", column: "scenario_name" });
    expect(parseReference("inputs.rain.mm")).toEqual({ kind: "stacked", column: "rain.mm" });
    // The dataset itself, a name no widget takes.
    expect(parseReference("inputs")).toEqual({ kind: "dataset" });
    // What the owner first named them would be widgets, or a column of input_1.
    expect(parseReference("scenario_colors")).toEqual({ kind: "widget", name: "scenario_colors" });
    expect(parseReference("scenario")).toEqual({ kind: "widget", name: "scenario" });
    expect(parseReference("input_1.scenario_color")).toEqual({ kind: "input", slot: 1, column: "scenario_color" });
  });

  test("closing up circles: an input's scenario chip follows its circle, and the deleted one reports itself", () => {
    const code = '{"a": "[!! scenario input_0 !!]", "b": "[!! scenario input_1 !!]", "c": [!! scenario input_2 !!], "d": [!! scenario colors !!]}';
    expect(renumberInputReferences(code, 1, "json")).toBe(
      '{"a": "[!! scenario input_0 !!]", "b": "[!! scenario input_? !!]", "c": [!! scenario input_1 !!], "d": [!! scenario colors !!]}',
    );
  });

  test("after closing up, an input's scenario chip writes the color of the box its input comes from", () => {
    // Routes 0, 1 and 2 feed the map; route 1 is deleted, so route 2 is now input_1.
    const code = renumberInputReferences('{"color": "[!! scenario input_2 !!]"}', 1, "json");
    const inputs: InputScope[] = [
      { slot: 0, scenario: { scenario: "fastest", name: "Fastest route", color: "#42A5F5", rank: 0 } },
      { slot: 1, scenario: { scenario: "weather-aware", name: "Weather-aware route", color: "#00838F", rank: 1 } },
    ];
    expect(resolveReferences(code, { widgets: [], inputs }, "json")).toEqual({
      code: '{"color": "#00838F"}',
      problems: [],
    });
  });
});

/**
 * A spec read for its shape before its chips are resolved (what an Autark
 * document declares): each chip standing on its own is held by a string of
 * itself, so any bare chip, a list or a scale included, leaves it JSON.
 * `with_chip_placeholders` in `code_references.py` does the same.
 */
describe("withChipPlaceholders", () => {
  test("each chip standing on its own is held by a string of its own text; one inside a string is left", () => {
    const spec = '{"encoding": {"x": {"field": "scenario_name", "sort": [!! scenario order !!]}, '
      + '"color": {"field": "scenario_name", "scale": [!! scenario colors !!]}, "y": {"field": "[!! inputs.sunlight !!]"}}, '
      + '"width": [!! size !!], "title": "Sun in \\"[!! season !!]\\""}';
    expect(() => JSON.parse(spec)).toThrow();
    const held = JSON.parse(withChipPlaceholders(spec));
    expect(held.encoding.x.sort).toBe("[!! scenario order !!]");
    expect(held.encoding.color.scale).toBe("[!! scenario colors !!]");
    expect(held.encoding.y.field).toBe("[!! inputs.sunlight !!]");
    expect(held.width).toBe("[!! size !!]");
    expect(held.title).toBe('Sun in "[!! season !!]"');
  });

  test("a spec with no chip standing on its own is itself", () => {
    expect(withChipPlaceholders('{"mark": "bar"}')).toBe('{"mark": "bar"}');
    expect(withChipPlaceholders('{"title": "[!! season !!]"}')).toBe('{"title": "[!! season !!]"}');
  });
});

describe("a Vega-Lite spec nested 5,000 deep", () => {
  // The browser reads a spec's places walking it, and a walk that deep
  // overflowed the stack, in the Widgets tab's render too.
  test("writes its names as they are, and does not overflow the stack", () => {
    const deep = '{"a": '.repeat(5000) + '{"field": "[!! y !!]"}' + "}".repeat(5000);
    const scope = { widgets: normalizeWidgets([{ name: "y", type: "text", default: "rain.mm" }]), inputs: [] };
    const result = resolveReferences(deep, scope, "json", "vega-lite");
    expect(result.problems).toEqual([]);
    expect(result.code).toBe(deep.replace("[!! y !!]", "rain.mm"));
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
