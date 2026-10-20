/**
 * A Vega-Lite chart's inputs stacked as the dataset `inputs` (#662): every
 * input's rows in circle order, each under its circle, its box's id and its
 * box's name; a column one input lacks is empty in its rows, and a value is a
 * row under `value`.
 *
 * `stackedInputs.cases.json` holds inputs and exactly the rows or the refusal
 * they give, and one input's own rows. This checks the browser's `stackInputs`
 * and `inputRows` against it; `test_scenario_inputs.py` checks Python's
 * `stack_inputs` and `input_rows`, which an exported notebook calls, against
 * the same file.
 */
import cases from "../../utils/scenarios/stackedInputs.cases.json";
import { inputRows, stackInputs, type StackEntry } from "../../utils/scenarios/stackedInputs";

type Case = { name: string; inputs: StackEntry[]; rows?: unknown[]; refusal?: string };
const all = cases.cases as Case[];

describe("stackInputs, against the cases Python's stack_inputs reads too", () => {
  test.each(all.filter((c) => c.rows).map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(stackInputs(c.inputs)).toEqual({ rows: c.rows });
  });

  test.each(all.filter((c) => c.refusal).map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(stackInputs(c.inputs)).toEqual({ refusal: c.refusal });
  });

  test("every case gives rows or a refusal, and the refusals name the dataset", () => {
    for (const c of all) expect(Boolean(c.rows) !== Boolean(c.refusal)).toBe(true);
    for (const c of all.filter((one) => one.refusal)) expect(c.refusal).toMatch(/^The dataset "inputs"/);
  });
});

describe("stackInputs leaves its inputs as they were", () => {
  test("the rows it gives are its own: an input's row is not written to", () => {
    const row = { segment: "r1", sunlight: 5, __input__: 3 };
    const out = stackInputs([{ scenario: "s-base", name: "Baseline", value: [row] }]) as { rows: any[] };
    expect(row).toEqual({ segment: "r1", sunlight: 5, __input__: 3 });
    expect(out.rows[0]).not.toBe(row);
    expect(out.rows[0]).toEqual({ segment: "r1", sunlight: 5, __input__: 0, scenario: "s-base", scenario_name: "Baseline" });
  });

  test("a number that is none is empty, as Python writes it", () => {
    const out = stackInputs([{ scenario: "s-base", name: "Baseline", value: [{ sunlight: Number.NaN }] }]);
    expect(out).toEqual({ rows: [{ sunlight: null, __input__: 0, scenario: "s-base", scenario_name: "Baseline" }] });
  });
});

describe("inputRows: one input's own rows, against the cases Python's input_rows reads too", () => {
  type RowsCase = { name: string; value: unknown; rows: unknown[] };
  test.each((cases.inputRows as RowsCase[]).map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(inputRows(c.value)).toEqual(c.rows);
  });
});
