/**
 * The Map Edits node's expressions (`utils/editFeatures/editExpr`) and its
 * edit log applied in the browser (`utils/editFeatures/applyEdits`), on the
 * cases `editExpr.cases.json` holds. `utk_curio/sandbox/tests/test_feature_edits.py`
 * runs the same cases through `edit_expr.py` and `curio_edit_features`, so the
 * node's table and a run read a condition, and apply an edit, alike.
 */
import fs from "fs";
import path from "path";
import shared from "../../utils/editFeatures/editExpr.cases.json";
import { evaluate, exprProblem, ExprError, parseExpr } from "../../utils/editFeatures/editExpr";
import { applyEdits } from "../../utils/editFeatures/applyEdits";
import { normalizeEditFeatures } from "../../utils/editFeatures/editFeatures";

type Row = Record<string, unknown>;
type ExpressionCase = { expr: string; row: Row; value: unknown };
type EditCase = {
  name: string;
  key: string;
  features: Row[];
  edits: unknown[];
  expected: Row[];
  counts: { remove: number; set: number; restore: number };
};

const expressions = shared.expressions as unknown as ExpressionCase[];
const edits = shared.edits as unknown as EditCase[];

describe("an expression over one feature's columns", () => {
  test.each(expressions.map((c) => [c.expr, c] as const))("%s", (_expr, c) => {
    expect(evaluate(parseExpr(c.expr), c.row)).toEqual(c.value);
  });

  test.each(shared.refusals.map((text) => [text] as const))("refuses %p", (text) => {
    expect(() => parseExpr(text)).toThrow(ExprError);
    expect(exprProblem(text)).toEqual(expect.any(String));
  });

  test("an expression it reads has no problem", () => {
    expect(exprProblem("height > 100 and levels >= 30")).toBeNull();
  });

  test("is read by its own parser, never by eval or Function", () => {
    const source = fs.readFileSync(path.resolve(__dirname, "../../utils/editFeatures/editExpr.ts"), "utf8");
    expect(source).not.toMatch(/\beval\s*\(|\bFunction\s*\(|new\s+Function\b/);
  });
});

describe("the edit log applied in the browser", () => {
  test.each(edits.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const settings = normalizeEditFeatures({ key: c.key, edits: c.edits });
    // Every entry of a case is one the node keeps.
    expect(settings?.edits).toHaveLength(c.edits.length);
    const { state, counts } = applyEdits(c.features, settings!.edits!, c.key);
    expect(state.filter((row) => row !== null)).toEqual(c.expected);
    expect(counts).toEqual(c.counts);
  });

  test("a feature no edit touches stays the same object, and a removed one is null in its place", () => {
    const rows: Row[] = [{ id: 1, h: 1 }, { id: 2, h: 1 }, { id: 3, h: 1 }];
    const { state } = applyEdits(rows, [{ op: "offset", ids: [2], column: "h", value: 1 }, { op: "remove", ids: [3] }], "id");
    expect(state[0]).toBe(rows[0]);
    expect(state[1]).toEqual({ id: 2, h: 2 });
    expect(state[2]).toBeNull();
    // The input's rows are never changed.
    expect(rows[1]).toEqual({ id: 2, h: 1 });
  });

  test("a condition or an expression that is not one throws, as a run refuses it", () => {
    expect(() => applyEdits([{ id: 1 }], [{ op: "remove", where: "id >" }], "id")).toThrow(ExprError);
    expect(() => applyEdits([{ id: 1 }], [{ op: "expr", ids: [1], column: "h", value: "open('x')" }], "id")).toThrow(ExprError);
  });
});
