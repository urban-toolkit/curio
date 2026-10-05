/**
 * The Compare Scenarios node's chart presets (#662): bars, grouped bars, lines,
 * points, a pie, lollipops and a table, each over the stacked table and colored
 * by scenario in the scenarios' own colors.
 *
 * `comparePresets.cases.json` holds one spec per preset. This checks that the
 * presets write exactly those specs; `test_compare_scenarios_node.py` checks
 * each against the Vega-Lite schema and the columns it reads.
 */
import cases from "../../utils/compare/comparePresets.cases.json";
import {
  chartColumns,
  compareChartSpec,
  resolveChart,
  scenarioScale,
  vegaField,
} from "../../utils/compare/comparePresets";
import { COMPARE_PRESETS, type CompareChart, type CompareInputLabel } from "../../utils/compare/compareSettings";
import type { ClassifiedColumn } from "../../utils/starterSpec";

const labels = cases.labels as CompareInputLabel[];
const columns = cases.columns as ClassifiedColumn[];

describe("the preset specs", () => {
  test("every preset has a case", () => {
    const covered = new Set(cases.cases.map((c) => (c.resolved as { preset: string }).preset));
    expect([...covered].sort()).toEqual([...COMPARE_PRESETS].sort());
  });

  test.each(cases.cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const resolved = resolveChart(c.chart as CompareChart, columns);
    expect(resolved).toEqual(c.resolved);
    const drawn = compareChartSpec(resolved, labels, columns);
    expect(drawn).toEqual({ spec: c.spec });
  });

  test("every spec colors by scenario, in the scenarios' colors and input order, and has no data block", () => {
    for (const c of cases.cases) {
      const text = JSON.stringify(c.spec);
      expect(text).toContain('"scale":{"domain":["Baseline","Twice as tall"],"range":["#2a9d8f","#e76f51"]}');
      expect((c.spec as Record<string, unknown>).data).toBeUndefined();
    }
  });
});

describe("resolveChart", () => {
  test("bars of the first measure, and a table when there is no measure", () => {
    expect(resolveChart(undefined, columns)).toEqual({ preset: "bar", y: "hour", aggregate: "mean" });
    expect(resolveChart(undefined, [{ name: "segment", role: "nominal" }])).toEqual({ preset: "table", aggregate: null });
  });

  test("a column the table no longer has is chosen again", () => {
    expect(resolveChart({ preset: "scatter", x: "gone", y: "sunlight" }, columns)).toEqual({
      preset: "scatter", x: "hour", y: "sunlight", aggregate: null,
    });
  });

  test("a preset that needs a column the table lacks says why instead of drawing", () => {
    const only = [{ name: "sunlight", role: "quantitative" }] as ClassifiedColumn[];
    const drawn = compareChartSpec(resolveChart({ preset: "grouped-bar" }, only), labels, only);
    expect(drawn).toEqual({ problem: "Grouped bars need a second column the stacked table does not have. Pick another chart." });
    const none = compareChartSpec(resolveChart({ preset: "bar" }, []), labels, []);
    expect(none).toEqual({ problem: "The stacked table has no number column to chart. Pick Table, or count rows." });
  });
});

describe("chartColumns", () => {
  test("leaves out the scenario columns and the geometry, which no preset reads as a field", () => {
    const read = chartColumns(
      { scenario: "object", scenario_name: "object", segment: "object", sunlight: "float64", geometry: "geometry" },
      [{ scenario: "s1", scenario_name: "Baseline", segment: "r1", sunlight: 1 }],
      "geometry",
    );
    expect(read).toEqual([
      { name: "segment", role: "nominal" },
      { name: "sunlight", role: "quantitative" },
    ]);
  });
});

describe("helpers", () => {
  test("a column name's dots and brackets are its own", () => {
    expect(vegaField("a.b[0]")).toBe("a\\.b\\[0\\]");
  });

  test("each scenario name once, with the color of its first input", () => {
    expect(
      scenarioScale([
        { name: "Baseline", color: "#111111" },
        { name: "Tall", color: "#222222" },
        { name: "Baseline", color: "#333333" },
      ]),
    ).toEqual({ domain: ["Baseline", "Tall"], range: ["#111111", "#222222"] });
  });
});
