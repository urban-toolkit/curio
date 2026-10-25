/**
 * What a play posts, against what a run on the server sends. An owner's kept
 * output is found again, when the dataflow reopens, by a key of both
 * (`runs/kept.py` `step_key`), so they must agree. The cases are in
 * `providers/flow/playCode.cases.json`, which
 * `utk_curio/backend/tests/test_runs/test_play_code_cases.py` reads too.
 */
import cases from "../../providers/flow/playCode.cases.json";
import { playIndent } from "../../PythonInterpreter";
import { executionInputRef } from "../../utils/flowOutputRef";

describe("what a play posts", () => {
  test.each(cases.code.map((c) => [c.name, c]))("the code: %s", (_name, c) => {
    expect(playIndent(c.code)).toBe(c.posted);
  });

  test.each(cases.inputs.map((c) => [c.name, c]))("the input: %s", (_name, c) => {
    expect(executionInputRef(c.canvas)).toEqual(c.posted);
  });
});
