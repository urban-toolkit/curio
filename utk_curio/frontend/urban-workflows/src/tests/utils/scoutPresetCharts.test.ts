/**
 * Scout's charts of the Compare Scenarios node's seven chart presets (the plan
 * answering komar41's review, step 6.2): Bars, Grouped bars, Lines, Points,
 * Pie, Lollipops and Table, each a Vega-Lite template whose columns, Combine
 * and axis titles are widgets.
 *
 * A one-time migration test: each template, with its widgets set as a case of
 * `comparePresets.cases.json` says, resolves to the spec the Compare node's
 * Chart tab wrote for that case, up to three things:
 *
 * - its `data` block, which names the dataset `inputs`, where the Chart tab
 *   handed the Compare node's stacked table in as `input_0`;
 * - what `withScenarioScales` fills on `scenario_name`, the boxes' colors and
 *   order, which it fills in both;
 * - how the y values are combined. Vega-Lite's `aggregate` has no "none", and
 *   a chip only writes text, so a template cannot leave the key out for None
 *   or the field out for a count of rows. It combines in its transforms
 *   (`combineBlock`) and plots the combined value, `curio_value`, under the
 *   title the Chart tab gave the aggregate it wrote on the channel.
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
import { AGGREGATE_LABELS, PRESET_FIELDS, PRESET_LABELS } from "../../utils/compare/comparePresets";
import {
  COMPARE_AGGREGATES,
  COMPARE_PRESETS,
  type CompareAggregate,
  type CompareInputLabel,
  type ComparePreset,
} from "../../utils/compare/compareSettings";
import { withScenarioScales } from "../../utils/compare/scenarioScales";
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

/** The presets whose y values are combined by more than one row: grouped bars
 *  and lines combine per category or x value too. */
const COMBINED_BY: Partial<Record<ComparePreset, "x">> = { "grouped-bar": "x", line: "x" };

interface Case {
  name: string;
  resolved: { preset: ComparePreset; x?: string; y?: string; aggregate: CompareAggregate | null };
  spec: Json;
}

const CASES = cases.cases as unknown as Case[];
const labels = cases.labels as CompareInputLabel[];

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

function at(spec: Json, where: (string | number)[]): Json {
  return where.reduce((node: any, key) => node[key], spec);
}

function put(spec: Json, where: (string | number)[], value: Json): void {
  const parent = at(spec, where.slice(0, -1));
  parent[where[where.length - 1]] = value;
}

/**
 * How a template combines its y values, once its chips are written: every
 * aggregate Combine offers, per scenario (and per *groupby*'s other columns),
 * or, for None, per row, then the one Combine picks as `curio_value`.
 */
function combineBlock(column: string, groupby: string[], label: string): Json[] {
  return [
    { window: [{ op: "row_number", as: "curio_row" }] },
    { calculate: `'${label}' === 'None' ? datum.curio_row : 0`, as: "curio_group" },
    {
      aggregate: [
        { op: "mean", field: column, as: "curio_mean" },
        { op: "sum", field: column, as: "curio_sum" },
        { op: "median", field: column, as: "curio_median" },
        { op: "min", field: column, as: "curio_min" },
        { op: "max", field: column, as: "curio_max" },
        { op: "count", as: "curio_count" },
      ],
      groupby: [...groupby, "curio_group"],
    },
    {
      calculate:
        "({'Mean': datum.curio_mean, 'Sum': datum.curio_sum, 'Median': datum.curio_median, " +
        "'Minimum': datum.curio_min, 'Maximum': datum.curio_max, 'Count of rows': datum.curio_count, " +
        `'None': datum.curio_max})['${label}']`,
      as: "curio_value",
    },
  ];
}

/** The widgets as *c* says: its columns, its Combine and the titles the Chart
 *  tab wrote. */
function widgetValues(c: Case): Record<string, WidgetValue> {
  const { preset, x, y, aggregate } = c.resolved;
  const spec = c.spec;
  const where = MEASURES[preset];
  const measureTitle = where ? at(spec, where[0]).title : undefined;
  const combine = aggregate ? AGGREGATE_LABELS[aggregate] : undefined;
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
 * The spec Compare's Chart tab wrote for *c*, as the template writes it: a
 * channel that held the aggregate holds `curio_value` under the same title,
 * and the transforms combine the y values. Vega-Lite draws the dots of a plot
 * it does not aggregate see-through, so Lollipops' dots say how see-through
 * they are, as Compare's were drawn: solid when combined, see-through for None.
 */
function expectedFromCompare(c: Case): Json {
  const { preset, x, y, aggregate } = c.resolved;
  const spec = clone(c.spec);
  const where = MEASURES[preset];
  if (!where) return spec;
  for (const path of where) {
    const { field, aggregate: written, type, title, ...kept } = at(spec, path);
    // What Compare wrote there: the y column under the case's aggregate, or
    // the count of rows, which reads no column.
    expect([field, written, type]).toEqual([
      aggregate === "count" ? undefined : y,
      aggregate === "none" ? undefined : aggregate,
      "quantitative",
    ]);
    put(spec, path, { field: "curio_value", type: "quantitative", title, ...kept });
  }
  const label = AGGREGATE_LABELS[aggregate!];
  const groupby = COMBINED_BY[preset] ? ["scenario_name", x!] : ["scenario_name"];
  spec.transform = combineBlock(y!, groupby, label);
  if (preset === "lollipop") spec.layer[1].mark.opacity = { expr: `'${label}' === 'None' ? 0.7 : 1` };
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

  test("offers the Chart tab's choices in its order, with each preset's default", () => {
    expect(combining).toEqual(Object.keys(MEASURES));
    for (const preset of COMPARE_PRESETS) {
      const widget = template(TEMPLATE_OF[preset]).widgets.find((w) => w.name === "combine");
      const fallback = PRESET_FIELDS[preset].aggregate;
      if (fallback === null) {
        expect(widget).toBeUndefined();
        continue;
      }
      expect(widget).toMatchObject({ type: "choice", label: "Combine", default: AGGREGATE_LABELS[fallback] });
      expect(widget?.options?.choices).toEqual(COMPARE_AGGREGATES.map((aggregate) => AGGREGATE_LABELS[aggregate]));
    }
  });

  test("each choice plots the aggregate the Chart tab wrote for it, and None each row as it is", () => {
    for (const preset of combining) {
      for (const aggregate of COMPARE_AGGREGATES) {
        const label = AGGREGATE_LABELS[aggregate];
        const [, group, combined, picked] = drawn(TEMPLATE_OF[preset], { combine: label }).transform;
        const lookup = Object.fromEntries(
          [...String(picked.calculate).matchAll(/'([^']+)': datum\.(\w+)/g)].map((m) => [m[1], m[2]]),
        );
        const ops = Object.fromEntries(combined.aggregate.map((op: Json) => [op.as, op.op]));
        expect(Object.keys(lookup)).toEqual(COMPARE_AGGREGATES.map((a) => AGGREGATE_LABELS[a]));
        expect(picked.calculate.endsWith(`['${label}']`)).toBe(true);
        expect(group.calculate).toBe(`'${label}' === 'None' ? datum.curio_row : 0`);
        // None makes each row a group of its own, whose maximum is its value.
        expect(ops[lookup[label]]).toBe(aggregate === "none" ? "max" : aggregate);
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
  const boxes: CompareInputLabel[] = [
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
