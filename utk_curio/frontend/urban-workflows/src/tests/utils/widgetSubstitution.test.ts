/**
 * How a node's `[!! name !!]` references become its widgets' values (#662).
 *
 * The cases live in `utils/widgets/widgetSubstitution.cases.json`, which
 * `utk_curio/backend/tests/test_execution/test_widget_substitution.py` reads
 * too: the headless runner must write the same code the browser does.
 */
import cases from "../../utils/widgets/widgetSubstitution.cases.json";
import {
  describeReferenceProblems,
  findWidgetReferences,
  resolveWidgetReferences,
  widgetLiteral,
  type WidgetLanguage,
} from "../../utils/widgets/widgetSubstitution";
import { normalizeWidgets } from "../../utils/widgets/widgetModel";

type Case = {
  name: string;
  language: WidgetLanguage;
  code: string;
  widgets: unknown[];
  expected: string;
  problems?: string[];
};

describe("the shared substitution cases", () => {
  test.each((cases.cases as Case[]).map((c) => [c.name, c]))("%s", (_name, c) => {
    const result = resolveWidgetReferences(c.code, normalizeWidgets(c.widgets), c.language);
    expect(result.code).toBe(c.expected);
    expect(result.problems.map((p) => p.message)).toEqual(c.problems ?? []);
  });

  test("the table covers every language", () => {
    const languages = new Set((cases.cases as Case[]).map((c) => c.language));
    expect([...languages].sort()).toEqual(["javascript", "json", "python"]);
  });
});

describe("references", () => {
  test("found with their offsets and trimmed names", () => {
    const code = "a = [!!  x !!] + [!! y!!]";
    expect(findWidgetReferences(code)).toEqual([
      { start: 4, end: 14, inner: "x" },
      { start: 17, end: 25, inner: "y" },
    ]);
  });

  test("problems read as one message, a line each", () => {
    const { problems } = resolveWidgetReferences("[!! a !!] [!! b$X$1 !!]", [], "python");
    expect(describeReferenceProblems(problems).split("\n")).toHaveLength(2);
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
