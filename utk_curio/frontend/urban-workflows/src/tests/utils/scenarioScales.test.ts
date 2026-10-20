/**
 * A Vega-Lite chart draws its scenarios from their labels: every color, fill
 * and stroke on `scenario_name` in the scenarios' colors (a text mark's in the
 * shades a table writes text in), every axis, offset and facet on it in the
 * order of the inputs, over whatever the spec writes for that column.
 *
 * `scenarioScales.cases.json` holds the specs and what they become. This checks
 * that `withScenarioScales` writes exactly those; `test_scenario_inputs.py`
 * checks each against the Vega-Lite schema and the columns it reads.
 */
import cases from "../../utils/scenarios/scenarioScales.cases.json";
import { scenarioScale, tableTextColor, type ScenarioLabel } from "../../utils/scenarios/scenarioColors";
import { withScenarioScales } from "../../utils/scenarios/scenarioScales";

const labels = cases.labels as ScenarioLabel[];

describe("a chart's scenarios drawn from their labels", () => {
  test.each(cases.cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const written = JSON.parse(JSON.stringify(c.spec));
    expect(withScenarioScales(c.spec, labels)).toEqual(c.filled);
    // The spec as written is left as it was.
    expect(c.spec).toEqual(written);
  });

  test.each(cases.untouched.map((c) => [c.name, c] as const))("%s: the spec itself", (_name, c) => {
    expect(withScenarioScales(c.spec, labels)).toBe(c.spec);
  });

  test("no labels, no scenarios to draw: every spec as written", () => {
    for (const c of [...cases.cases, ...cases.untouched]) expect(withScenarioScales(c.spec, [])).toBe(c.spec);
  });

  test("the scenarios run in input order, which is not their names' order", () => {
    const names = labels.map((label) => label.name);
    expect(names).not.toEqual([...names].sort());
  });
});

describe("the colors are the presets' own", () => {
  const filledScale = (name: string, pick: (spec: any) => any) =>
    pick(cases.cases.find((c) => c.name === name)!.filled).scale;

  test("a mark's are scenarioScale's, as every preset colors by scenario", () => {
    const bars = filledScale("bars colored by scenario, with no scale written", (spec) => spec.encoding.color);
    expect(bars).toEqual(scenarioScale(labels));
    const drawn = withScenarioScales(cases.cases[0].spec, labels) as any;
    expect(drawn.encoding.color.scale).toEqual(scenarioScale(labels));
  });

  test("a text mark's are a table's text colors: a light one in its shade that reads on white", () => {
    const { domain, range } = scenarioScale(labels);
    const text = filledScale(
      "a text mark in the shades a table writes, its rows in input order",
      (spec) => spec.encoding.color,
    );
    expect(text).toEqual({ domain, range: range.map(tableTextColor) });
    expect(text.range).not.toEqual(scenarioScale(labels).range);
  });
});
