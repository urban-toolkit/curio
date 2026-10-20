/**
 * Scout's charts of the Compare Scenarios node's seven chart presets (the plan
 * answering komar41's review, step 6.2): Bars, Grouped bars, Lines, Points,
 * Pie, Lollipops and Table, each a Vega-Lite template whose columns, Combine
 * and axis titles are widgets.
 *
 * A one-time migration test: each template, with its widgets set as a case of
 * `comparePresets.cases.json` says, resolves to the spec the Compare node's
 * Chart tab wrote for that case, up to its `data` block, which names the
 * dataset `inputs` where the Chart tab handed the Compare node's stacked table
 * in as `input_0`, and what `withScenarioScales` fills on `scenario_name`.
 *
 * Combine writes Vega-Lite's own aggregate on the measure, `"aggregate":
 * "[!! combine !!]"`, so its choices are Vega-Lite's: mean, sum, median, min,
 * max and count. Two of Compare's cases read differently, and
 * `expectedFromCompare` says how, in one place: Compare's None has no
 * aggregate in Vega-Lite, so a case of it sets mean and expects the measure
 * to write it; and Compare's count of rows named no column, where the chip
 * writes the y column beside the count, which Vega-Lite's count ignores.
 *
 * Step 6.4 deletes Compare and its cases, and re-pins each template to cases
 * of its own then: `expectedFromCompare` gives way to a cases file of
 * (template, widgets, spec), written once from what it returns.
 *
 * Also here: Combine's choices and each preset's default, and a spec its user
 * edited, which keeps the edit and still draws its scenarios in their boxes'
 * colors.
 */
import * as fs from "fs";
import * as path from "path";
import cases from "../../utils/compare/comparePresets.cases.json";
import { PRESET_FIELDS, PRESET_LABELS } from "../../utils/compare/comparePresets";
import {
  COMPARE_AGGREGATES,
  COMPARE_PRESETS,
  type CompareAggregate,
  type ComparePreset,
} from "../../utils/compare/compareSettings";
import type { ScenarioLabel } from "../../utils/scenarios/scenarioColors";
import { withScenarioScales } from "../../utils/scenarios/scenarioScales";
import { resolveReferences } from "../../utils/references/codeReferences";
import { normalizeWidgets, type WidgetDef, type WidgetValue } from "../../utils/widgets/widgetModel";

const REPO_ROOT = path.resolve(__dirname, "../../../../../..");
/** Scout, as the repository ships it. */
const SCOUT = path.join(REPO_ROOT, "packages", "curio.scout@1");

type Json = Record<string, any>;

interface Template {
  id: string;
  label: string;
  source: string;
  widgets: WidgetDef[];
}

/** One of Scout's templates. Read when asked, so a checkout without it fails
 *  test by test. */
function template(id: string): Template {
  const manifest = JSON.parse(fs.readFileSync(path.join(SCOUT, "manifest.json"), "utf-8"));
  const found = (manifest.templates as Template[]).find((t) => t.id === id);
  if (!found) throw new Error(`Scout has no template ${id}`);
  return found;
}

function source(id: string): string {
  return fs.readFileSync(path.join(SCOUT, template(id).source), "utf-8");
}

/** Each Compare preset, and the Scout template that draws it. */
const TEMPLATE_OF: Record<ComparePreset, string> = {
  bar: "bars",
  "grouped-bar": "grouped-bars",
  line: "lines",
  scatter: "points",
  pie: "pie",
  lollipop: "lollipops",
  table: "table",
};

/** Where each preset that combines its y values wrote them: one channel, or
 *  the arcs' and their values' for a pie, or the stems' and the dots' for
 *  lollipops. */
const MEASURES: Partial<Record<ComparePreset, (string | number)[][]>> = {
  bar: [["encoding", "y"]],
  "grouped-bar": [["encoding", "y"]],
  line: [["encoding", "y"]],
  pie: [["encoding", "theta"], ["layer", 1, "encoding", "text"]],
  lollipop: [["layer", 0, "encoding", "x"], ["layer", 1, "encoding", "x"]],
};

/** Combine's choices: Vega-Lite's aggregates among Compare's, all but None. */
const COMBINE_CHOICES = COMPARE_AGGREGATES.filter((aggregate) => aggregate !== "none");

interface Case {
  name: string;
  resolved: { preset: ComparePreset; x?: string; y?: string; aggregate: CompareAggregate | null };
  spec: Json;
}

const CASES = cases.cases as unknown as Case[];
const labels = cases.labels as ScenarioLabel[];

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

function at(spec: Json, where: (string | number)[]): Json {
  return where.reduce((node: any, key) => node[key], spec);
}

/** Combine as a case sets it: its aggregate, or mean for Compare's None. */
const combineOf = (aggregate: CompareAggregate | null) => (aggregate === "none" ? "mean" : aggregate);

/** The widgets as *c* says: its columns, its Combine and the titles the Chart
 *  tab wrote. */
function widgetValues(c: Case): Record<string, WidgetValue> {
  const { preset, x, y, aggregate } = c.resolved;
  const spec = c.spec;
  const where = MEASURES[preset];
  const measureTitle = where ? at(spec, where[0]).title : undefined;
  const combine = combineOf(aggregate);
  switch (preset) {
    case "bar":
      return { y: y!, combine: combine!, y_title: measureTitle };
    case "grouped-bar":
      return { x: x!, y: y!, combine: combine!, x_title: spec.encoding.x.title, y_title: measureTitle };
    case "line":
      return {
        x: x!, x_type: spec.encoding.x.type, y: y!, combine: combine!,
        x_title: spec.encoding.x.title, y_title: measureTitle,
      };
    case "scatter":
      return { x: x!, y: y!, x_title: spec.encoding.x.title, y_title: spec.encoding.y.title };
    case "pie":
      return { value: y!, combine: combine!, value_title: measureTitle };
    case "lollipop":
      return { value: y!, combine: combine!, x_title: measureTitle };
    case "table":
      return { columns: spec.transform[2].fold };
  }
}

/**
 * The spec Compare's Chart tab wrote for *c*, as the template writes it. The
 * same, but where its measure differs from Vega-Lite's own aggregate: None,
 * which Vega-Lite has no aggregate for, is written as mean, and a count of
 * rows names the y column too, which Vega-Lite's count ignores.
 */
function expectedFromCompare(c: Case): Json {
  const { preset, y, aggregate } = c.resolved;
  const spec = clone(c.spec);
  for (const where of MEASURES[preset] ?? []) {
    const measure = at(spec, where);
    if (aggregate === "none") {
      expect(measure.aggregate).toBeUndefined();
      measure.aggregate = "mean";
    }
    if (aggregate === "count") {
      expect(measure.field).toBeUndefined();
      measure.field = y;
    }
  }
  return spec;
}

/** *id*'s spec, its widgets set to *values*, as a chart draws it: its chips
 *  written and its scenarios in the colors and order *boxes* give. */
function drawn(id: string, values: Record<string, WidgetValue>, boxes = labels, text = source(id)): Json {
  const widgets = template(id).widgets.map((w) => (w.name in values ? { ...w, value: values[w.name] } : w));
  const { code, problems } = resolveReferences(text, { widgets: normalizeWidgets(widgets), inputs: [], shared: [] }, "json");
  expect(problems).toEqual([]);
  return withScenarioScales(JSON.parse(code), boxes) as Json;
}

describe("each preset's template draws the spec Compare's Chart tab wrote", () => {
  test("every preset has a template, labelled as the Chart tab labels it", () => {
    expect(Object.keys(TEMPLATE_OF).sort()).toEqual([...COMPARE_PRESETS].sort());
    for (const preset of COMPARE_PRESETS) expect(template(TEMPLATE_OF[preset]).label).toBe(PRESET_LABELS[preset]);
  });

  test("every preset has a case", () => {
    expect([...new Set(CASES.map((c) => c.resolved.preset))].sort()).toEqual([...COMPARE_PRESETS].sort());
  });

  test.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const spec = drawn(TEMPLATE_OF[c.resolved.preset], widgetValues(c));
    expect(spec.data).toEqual({ name: "inputs" });
    delete spec.data;
    expect(spec).toEqual(expectedFromCompare(c));
  });
});

describe("Combine", () => {
  const combining = COMPARE_PRESETS.filter((preset) => PRESET_FIELDS[preset].aggregate !== null);

  test("offers Vega-Lite's own aggregates, with each preset's default", () => {
    expect(combining).toEqual(Object.keys(MEASURES));
    expect(COMBINE_CHOICES).toEqual(["mean", "sum", "median", "min", "max", "count"]);
    for (const preset of COMPARE_PRESETS) {
      const widget = template(TEMPLATE_OF[preset]).widgets.find((w) => w.name === "combine");
      const fallback = PRESET_FIELDS[preset].aggregate;
      if (fallback === null) {
        expect(widget).toBeUndefined();
        continue;
      }
      expect(widget).toMatchObject({ type: "choice", label: "Combine", default: fallback });
      expect(widget?.options?.choices).toEqual(COMBINE_CHOICES);
    }
  });

  test("each choice is the aggregate written on every channel that draws the measure", () => {
    for (const preset of combining) {
      for (const aggregate of COMBINE_CHOICES) {
        const spec = drawn(TEMPLATE_OF[preset], { combine: aggregate });
        for (const where of MEASURES[preset]!) expect(at(spec, where).aggregate).toBe(aggregate);
        expect(spec.transform).toBeUndefined();
      }
    }
  });
});

describe("a chart whose spec its user edited", () => {
  // Dots with a range, as a user left it: bigger dots, colors of their own for
  // the scenarios, and a title.
  const ID = "dots-with-a-range";
  const edited = () => {
    const spec = JSON.parse(source(ID));
    spec.title = "Minutes of shadow per park";
    spec.layer[1].mark.size = 140;
    spec.layer[1].encoding.color.scale = { range: ["#000000", "#ffffff"] };
    return JSON.stringify(spec, null, 2);
  };
  const PARKS = { category: "park", value: "mean_min", x_title: "Mean shadow (minutes)", y_title: "" };
  const boxes: ScenarioLabel[] = [
    { scenario: "existing", name: "Existing", color: "#2a9d8f" },
    { scenario: "removed", name: "Towers removed", color: "#e76f51" },
    { scenario: "capped", name: "Height cap", color: "#6a4c93" },
  ];

  test("a widget change writes only its chips, and keeps every other character", () => {
    const text = edited();
    const between = text.split(/\[!!\s*.*?\s*!!\]/);
    const escape = (part: string) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const shape = new RegExp(`^${between.map(escape).join("(.*?)")}$`, "s");
    const widgets = template(ID).widgets.map((w) => ({ ...w, value: PARKS[w.name as keyof typeof PARKS] }));
    const { code } = resolveReferences(text, { widgets: normalizeWidgets(widgets), inputs: [], shared: [] }, "json");
    const written = shape.exec(code);
    expect(written).not.toBeNull();
    const chips = [...text.matchAll(/\[!!\s*(.*?)\s*!!\]/g)].map((m) => m[1]);
    expect(written!.slice(1)).toEqual(chips.map((name) => PARKS[name as keyof typeof PARKS]));
  });

  test("it keeps the edit and still draws its scenarios in their boxes' colors and order", () => {
    const spec = drawn(ID, PARKS, boxes, edited());
    expect(spec.title).toBe("Minutes of shadow per park");
    expect(spec.layer[1].mark.size).toBe(140);
    expect(spec.layer[1].encoding.color).toEqual({
      field: "scenario_name",
      type: "nominal",
      title: "Scenario",
      legend: { orient: "bottom" },
      scale: { domain: ["Existing", "Towers removed", "Height cap"], range: ["#2a9d8f", "#e76f51", "#6a4c93"] },
    });
    // A box renamed and recolored is drawn so, with nothing else moved.
    const renamed = boxes.map((box) => (box.scenario === "capped" ? { ...box, name: "Capped at 100 m", color: "#1b7837" } : box));
    const again = drawn(ID, PARKS, renamed, edited());
    expect(again.layer[1].encoding.color.scale).toEqual({
      domain: ["Existing", "Towers removed", "Capped at 100 m"],
      range: ["#2a9d8f", "#e76f51", "#1b7837"],
    });
    expect({ ...again, layer: [again.layer[0], { ...again.layer[1], encoding: { ...again.layer[1].encoding, color: null } }] })
      .toEqual({ ...spec, layer: [spec.layer[0], { ...spec.layer[1], encoding: { ...spec.layer[1].encoding, color: null } }] });
  });
});
