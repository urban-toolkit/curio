/**
 * The code a Compare Scenarios node writes for itself (#662): one line per
 * input, reading it through its chip under its scenario's id and name.
 *
 * `compareCode.cases.json` holds the code for a few sets of inputs. This
 * checks that the node writes exactly that, and that its chips resolve as a
 * Python node's do; `test_compare_scenarios_node.py` resolves the same code as
 * a run on the server does and runs it through the stacking step.
 */
import cases from "../../utils/compare/compareCode.cases.json";
import * as writer from "../../utils/compare/compareCode";
import { STACK_HELPER, stackCode } from "../../utils/compare/compareCode";
import { resolveReferences } from "../../utils/references/codeReferences";
import type { CompareInputLabel } from "../../utils/compare/compareSettings";

type CodeCase = { name: string; inputs: { slot: number; label: CompareInputLabel }[]; code: string };

describe("stackCode", () => {
  test.each((cases.cases as CodeCase[]).map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(stackCode(c.inputs)).toBe(c.code);
  });

  test("its chips read the inputs as any Python node's do: arg with one input, arg[i] with several", () => {
    const [two, one] = cases.cases as CodeCase[];
    const scope = (n: number) => ({ widgets: [], shared: [], inputs: Array.from({ length: n }, (_, slot) => ({ slot })) });
    const resolvedTwo = resolveReferences(two.code, scope(2), "python");
    expect(resolvedTwo.problems).toEqual([]);
    expect(resolvedTwo.code).toContain('("s-base", "Baseline", arg[0]),');
    expect(resolvedTwo.code).toContain('("s-tall", "Twice as tall", arg[1]),');
    expect(resolveReferences(one.code, scope(1), "python").code).toContain('("s-base", "Baseline", arg),');
  });

  test("a circle with no edge is a chip the run refuses, naming it", () => {
    const [two] = cases.cases as CodeCase[];
    const resolved = resolveReferences(two.code, { widgets: [], shared: [], inputs: [{ slot: 0 }] }, "python");
    expect(resolved.problems.map((p) => p.reference)).toEqual(["[!! input 1 !!]"]);
  });

  test("calls the sandbox's stacking step", () => {
    expect(stackCode([])).toContain(`return ${STACK_HELPER}([])`);
  });
});

describe("the layer read from an Autark node's several", () => {
  const [two] = cases.cases as CodeCase[];
  // Read through the module, so a checkout without the layer fails test by test.
  const { compareCode, differenceCode, keyOfCode, layerOfCode } = writer;

  test("the stacking code names it after the inputs, and reads back", () => {
    const code = stackCode(two.inputs, "table_osm_roads");
    expect(code.endsWith('], layer="table_osm_roads")\n')).toBe(true);
    expect(layerOfCode(code)).toBe("table_osm_roads");
    expect(layerOfCode(stackCode(two.inputs))).toBeUndefined();
  });

  test("the difference code names it before the key, and both read back", () => {
    const code = differenceCode(two.inputs, "osm_id", "table_osm_roads");
    expect(code.endsWith('], layer="table_osm_roads", key="osm_id")\n')).toBe(true);
    expect(layerOfCode(code)).toBe("table_osm_roads");
    expect(keyOfCode(code)).toBe("osm_id");
    expect(keyOfCode(differenceCode(two.inputs, undefined, "table_osm_roads"))).toBeUndefined();
  });

  test("compareCode hands it to the view's step", () => {
    expect(compareCode("chart", two.inputs, undefined, "roads")).toBe(stackCode(two.inputs, "roads"));
    expect(compareCode("difference", two.inputs, { key: "k" }, "roads")).toBe(differenceCode(two.inputs, "k", "roads"));
  });
});
