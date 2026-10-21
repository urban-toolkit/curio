/**
 * Scout's seven preset charts (the plan answering komar41's review, step 6.2):
 * Bars, Grouped bars, Lines, Points, Pie, Lollipops and Table, each a
 * Vega-Lite template whose columns, Combine and axis titles are widgets.
 *
 * Each template, with its widgets set as a case of
 * `scoutPresetCharts.cases.json` says, resolves to the case's spec, up to its
 * `data` block, which names the dataset `inputs` by its chip, `[!! inputs !!]`,
 * its scenario chips written
 * over the cases' two boxes: each channel on `scenario_name` takes their colors
 * or their order, as Curio's hidden fill gave them before the chips. The cases
 * are the specs the Compare Scenarios node's chart presets wrote for the same
 * settings, written out when the node was removed (step 6.4), with two
 * differences of Vega-Lite's own aggregate: Compare's None, which Vega-Lite has
 * no aggregate for, reads as mean, and a count of rows names the y column too,
 * which Vega-Lite's count ignores.
 *
 * Combine writes Vega-Lite's own aggregate on the measure, `"aggregate":
 * "[!! combine !!]"`, so its choices are Vega-Lite's: mean, sum, median, min,
 * max and count.
 *
 * Also here: Combine's choices and each chart's default, and a spec its user
 * edited, which keeps the edit and still draws its scenarios in their boxes'
 * colors through the chip it keeps, or in its own where the edit writes them.
 */
import * as fs from "fs";
import * as path from "path";
import cases from "./scoutPresetCharts.cases.json";
import type { ScenarioLabel } from "../../utils/scenarios/scenarioColors";
import {
  resolveReferences,
  withChipPlaceholders,
  type InputScope,
  type ReferenceScope,
} from "../../utils/references/codeReferences";
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

/** The seven preset charts, each by its template id, with its label. */
const LABELS: Record<string, string> = {
  bars: "Bars",
  "grouped-bars": "Grouped bars",
  lines: "Lines",
  points: "Points",
  pie: "Pie",
  lollipops: "Lollipops",
  table: "Table",
};

/** Where each chart that combines its y values writes them: one channel, or
 *  the arcs' and their values' for a pie, or the stems' and the dots' for
 *  lollipops. */
const MEASURES: Record<string, (string | number)[][]> = {
  bars: [["encoding", "y"]],
  "grouped-bars": [["encoding", "y"]],
  lines: [["encoding", "y"]],
  pie: [["encoding", "theta"], ["layer", 1, "encoding", "text"]],
  lollipops: [["layer", 0, "encoding", "x"], ["layer", 1, "encoding", "x"]],
};

/** Each chart's Combine by default: the sum for a pie, the mean for the others
 *  that combine, and none for Points and Table, which draw each row. */
const COMBINE_DEFAULTS: Record<string, string | null> = {
  bars: "mean",
  "grouped-bars": "mean",
  lines: "mean",
  points: null,
  pie: "sum",
  lollipops: "mean",
  table: null,
};

/** Combine's choices: Vega-Lite's own aggregates. */
const COMBINE_CHOICES = ["mean", "sum", "median", "min", "max", "count"];

interface Case {
  name: string;
  template: string;
  widgets: Record<string, WidgetValue>;
  spec: Json;
}

const CASES = cases.cases as unknown as Case[];
const labels = cases.labels as ScenarioLabel[];

function at(spec: Json, where: (string | number)[]): Json {
  return where.reduce((node: any, key) => node[key], spec);
}

/** The scope a chart over *boxes*, one per circle and listed in that order,
 *  resolves its chips in: its widgets set to *values*. */
function scopeOf(id: string, values: Record<string, WidgetValue>, boxes: ScenarioLabel[]): ReferenceScope {
  const widgets = template(id).widgets.map((w) => (w.name in values ? { ...w, value: values[w.name] } : w));
  const inputs: InputScope[] = boxes.map((box, slot) => ({ slot, scenario: { ...box, rank: slot } }));
  return { widgets: normalizeWidgets(widgets), inputs, shared: [] };
}

/** *id*'s spec, its widgets set to *values*, as a chart draws it: its chips
 *  written, its scenarios in the colors and order of *boxes*. */
function drawn(id: string, values: Record<string, WidgetValue>, boxes = labels, text = source(id)): Json {
  const { code, problems } = resolveReferences(text, scopeOf(id, values, boxes), "json");
  expect(problems).toEqual([]);
  return JSON.parse(code) as Json;
}

describe("each preset chart draws its case's spec", () => {
  test("every preset chart is a template, with its label", () => {
    for (const [id, label] of Object.entries(LABELS)) expect(template(id).label).toBe(label);
  });

  test("every preset chart has a case", () => {
    expect([...new Set(CASES.map((c) => c.template))].sort()).toEqual(Object.keys(LABELS).sort());
  });

  test.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    // Written with the dataset's chip, which the chart draws as that dataset.
    expect(JSON.parse(withChipPlaceholders(source(c.template))).data).toEqual({ name: "[!! inputs !!]" });
    const spec = drawn(c.template, c.widgets);
    expect(spec.data).toEqual({ name: "inputs" });
    delete spec.data;
    expect(spec).toEqual(c.spec);
  });
});

describe("Combine", () => {
  const combining = Object.keys(LABELS).filter((id) => COMBINE_DEFAULTS[id] !== null);

  test("offers Vega-Lite's own aggregates, with each chart's default", () => {
    expect(combining).toEqual(Object.keys(MEASURES));
    for (const id of Object.keys(LABELS)) {
      const widget = template(id).widgets.find((w) => w.name === "combine");
      const fallback = COMBINE_DEFAULTS[id];
      if (fallback === null) {
        expect(widget).toBeUndefined();
        continue;
      }
      expect(widget).toMatchObject({ type: "choice", label: "Combine", default: fallback });
      expect(widget?.options?.choices).toEqual(COMBINE_CHOICES);
    }
  });

  test("each choice is the aggregate written on every channel that draws the measure", () => {
    for (const id of combining) {
      for (const aggregate of COMBINE_CHOICES) {
        const spec = drawn(id, { combine: aggregate });
        for (const where of MEASURES[id]) expect(at(spec, where).aggregate).toBe(aggregate);
        expect(spec.transform).toBeUndefined();
      }
    }
  });
});

describe("a chart whose spec its user edited", () => {
  // Dots with a range, as a user left it: bigger dots and a title. Its
  // scenarios' scale is the chip the template writes.
  const ID = "dots-with-a-range";
  const SCALE_CHIP = '"scale": [!! scenario colors !!]';
  const edited = () => {
    const text = source(ID);
    expect(text).toContain(SCALE_CHIP);
    expect(text).toContain('"size": 60');
    return text.replace("{", '{\n  "title": "Minutes of shadow per park",').replace('"size": 60', '"size": 140');
  };
  /** The same edit, with colors of its own for the scenarios in the chip's place. */
  const ownColors = () => edited().replace(SCALE_CHIP, '"scale": {"range": ["#000000", "#ffffff", "#888888"]}');
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
    const scope = scopeOf(ID, PARKS, boxes);
    const { code } = resolveReferences(text, scope, "json");
    const written = shape.exec(code);
    expect(written).not.toBeNull();
    // A widget's chip writes its value; the scenarios' chip, their scale.
    const scale = resolveReferences("[!! scenario colors !!]", scope, "json").code;
    const chips = [...text.matchAll(/\[!!\s*(.*?)\s*!!\]/g)].map((m) => m[1]);
    expect(written!.slice(1)).toEqual(chips.map((name) => (name in PARKS ? PARKS[name as keyof typeof PARKS] : scale)));
  });

  test("it keeps the edit and still draws its scenarios in their boxes' colors and order, through its chip", () => {
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

  test("an edit that writes colors of its own in the chip's place draws those, whatever its boxes'", () => {
    const spec = drawn(ID, PARKS, boxes, ownColors());
    expect(spec.layer[1].encoding.color.scale).toEqual({ range: ["#000000", "#ffffff", "#888888"] });
  });
});
