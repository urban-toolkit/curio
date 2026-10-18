/**
 * The Compare Scenarios node's chart presets (#662): bars, grouped bars, lines,
 * points, a pie, lollipops and a table, each over the stacked table and colored
 * by scenario in the scenarios' own colors, a table's text in a shade of them
 * that reads on white.
 *
 * `comparePresets.cases.json` holds one spec per preset. This checks that the
 * presets write exactly those specs; `test_compare_scenarios_node.py` checks
 * each against the Vega-Lite schema and the columns it reads.
 */
import cases from "../../utils/compare/comparePresets.cases.json";
import {
  AGGREGATE_LABELS,
  PRESET_FIELDS,
  chartColumns,
  compareChartSpec,
  resolveChart,
  scenarioScale,
  vegaField,
} from "../../utils/compare/comparePresets";
import {
  COMPARE_AGGREGATES,
  COMPARE_PRESETS,
  type CompareChart,
  type CompareInputLabel,
} from "../../utils/compare/compareSettings";
import { SCENARIO_COLORS } from "../../utils/scenarios/scenarioEdits";
import type { ClassifiedColumn } from "../../utils/starterSpec";

const labels = cases.labels as CompareInputLabel[];
const columns = cases.columns as ClassifiedColumn[];

/** A `#rrggbb` color's contrast on white (WCAG 2), worked out here apart from the presets. */
function contrastOnWhite(color: string): number {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const value = parseInt(color.slice(at, at + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05);
}

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

describe("combining nothing, none", () => {
  test("Combine offers None after the aggregates", () => {
    expect(COMPARE_AGGREGATES[COMPARE_AGGREGATES.length - 1]).toBe("none");
    expect(AGGREGATE_LABELS.none).toBe("None");
  });

  test("every preset that combines plots each row's value as it is, under its column's name", () => {
    const combining = COMPARE_PRESETS.filter((preset) => PRESET_FIELDS[preset].aggregate !== null);
    expect(combining).toEqual(["bar", "grouped-bar", "line", "pie", "lollipop"]);
    for (const preset of combining) {
      const resolved = resolveChart({ preset, aggregate: "none" }, columns);
      expect(resolved.aggregate).toBe("none");
      const drawn = compareChartSpec(resolved, labels, columns);
      const text = JSON.stringify((drawn as { spec: unknown }).spec);
      expect(text).not.toContain('"aggregate"');
      expect(text).not.toContain(" of hour");
      expect(text).toContain('"field":"hour","type":"quantitative","title":"hour"');
    }
  });
});

describe("a pie writes each slice's value on it", () => {
  test("in white, over its arcs, reading what its slices measure", () => {
    const drawn = compareChartSpec(resolveChart({ preset: "pie", aggregate: "count" }, columns), labels, columns);
    const spec = (drawn as { spec: any }).spec;
    expect(spec.encoding.theta).toEqual({ aggregate: "count", type: "quantitative", title: "Rows", stack: true });
    expect(spec.layer).toHaveLength(2);
    const [arcs, values] = spec.layer;
    expect(arcs).toEqual({ mark: { type: "arc", tooltip: true } });
    expect(values.mark).toMatchObject({ type: "text", fill: "white" });
    expect(values.encoding.text).toEqual({ aggregate: "count", type: "quantitative", title: "Rows", format: ",.3~f" });
  });

  test("stacked by the arcs' own color field, so each value sits on its own slice", () => {
    // Vega-Lite orders a stack by the color channel's scale domain, and one by
    // any other channel (detail) by name: a value layer that stacked by detail
    // put Twice as tall's value on Baseline's slice. The text layer sets no
    // color or detail of its own, so it stacks on the color field it inherits.
    for (const aggregate of ["sum", "count", "none"] as const) {
      const drawn = compareChartSpec(resolveChart({ preset: "pie", aggregate }, columns), labels, columns);
      const spec = (drawn as { spec: any }).spec;
      expect(spec.encoding.color).toEqual({
        field: "scenario_name",
        type: "nominal",
        title: "Scenario",
        scale: { domain: ["Baseline", "Twice as tall"], range: ["#2a9d8f", "#e76f51"] },
      });
      for (const layer of spec.layer) {
        expect(Object.keys(layer.encoding ?? {}).filter((channel) => channel !== "text")).toEqual([]);
      }
    }
  });
});

describe("a table's text reads on white", () => {
  // The scenario comparison charts' green roofs: 1.6:1, 2.9:1 and 6.5:1 on white.
  const roofs: CompareInputLabel[] = [
    { name: "Extensive roof", color: "#a1d99b" },
    { name: "Semi-intensive roof", color: "#41ab5d" },
    { name: "Intensive roof", color: "#006d2c" },
  ];
  const tableScale = (scenarios: CompareInputLabel[]) => {
    const drawn = compareChartSpec(resolveChart({ preset: "table" }, columns), scenarios, columns) as { spec: any };
    return drawn.spec.encoding.color.scale;
  };

  test("a scenario color under 3:1 is drawn in its lightest shade that reaches 3:1, the others as they are", () => {
    const scale = tableScale(roofs);
    expect(scale.domain).toEqual(["Extensive roof", "Semi-intensive roof", "Intensive roof"]);
    expect(scale.range).toEqual(["#769e71", "#40a85b", "#006d2c"]);
    for (const color of scale.range) expect(contrastOnWhite(color)).toBeGreaterThanOrEqual(3);
  });

  test("Curio's eight default scenario colors reach 3:1, so a table draws them as they are", () => {
    expect(SCENARIO_COLORS).toHaveLength(8);
    for (const color of SCENARIO_COLORS) expect(contrastOnWhite(color)).toBeGreaterThanOrEqual(3);
    const defaults = SCENARIO_COLORS.map((color, i) => ({ name: `Scenario ${i + 1}`, color }));
    expect(tableScale(defaults).range).toEqual([...SCENARIO_COLORS]);
  });

  test("only a table's text: every other preset draws the scenarios' own colors", () => {
    for (const c of cases.cases) {
      if ((c.resolved as { preset: string }).preset === "table") continue;
      const drawn = compareChartSpec(resolveChart(c.chart as CompareChart, columns), roofs, columns) as { spec: unknown };
      expect(JSON.stringify(drawn.spec)).toContain('"range":["#a1d99b","#41ab5d","#006d2c"]');
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
