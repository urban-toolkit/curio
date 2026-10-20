/**
 * @jest-environment node
 */
/**
 * Scout's charts over a column whose name holds a dot or a bracket, such as
 * `rain.mm` (issue 1042). Vega-Lite reads a `.` or a `[` in a field as a path
 * into the row, so `rain.mm` is `mm` inside `rain`: a chip where Vega-Lite
 * reads a field writes the name escaped, `rain\.mm`, and anywhere else, a
 * title, a sort or an expression, the name as it is.
 *
 * Each chart is written as the canvas writes a Vega-Lite node's spec, compiled
 * with the vega-lite the app bundles, and run by vega without a renderer; what
 * it drew is read off its scene graph. Over the same rows, a chart draws the
 * same marks whether its columns' names hold a dot or not. It runs in Node's
 * environment, which needs no DOM: vega-lite's build reads `structuredClone`,
 * which jsdom's window does not have.
 */
import * as fs from "fs";
import * as path from "path";
import { resolveReferences } from "../../utils/references/codeReferences";
import { normalizeWidgets, type WidgetDef, type WidgetValue } from "../../utils/widgets/widgetModel";

// vega-lite's build asks for vega, whose package entry is an ES module, which
// Jest does not load: vega's UMD build is the same vega as CommonJS.
jest.mock("vega", () => require(require("path").resolve(__dirname, "../../../node_modules/vega/build/vega.js")), {
  virtual: true,
});

const NODE_MODULES = path.resolve(__dirname, "../../../node_modules");
const vega = require("vega");
const vegaLite = require(path.join(NODE_MODULES, "vega-lite/build/vega-lite.min.js"));

const REPO_ROOT = path.resolve(__dirname, "../../../../../..");
/** Scout, as the repository ships it. */
const SCOUT = path.join(REPO_ROOT, "packages", "curio.scout@1");

type Json = Record<string, any>;

interface Template {
  id: string;
  source: string;
  widgets: WidgetDef[];
}

/** One of Scout's templates, read when asked. */
function template(id: string): Template {
  const manifest = JSON.parse(fs.readFileSync(path.join(SCOUT, "manifest.json"), "utf-8"));
  const found = (manifest.templates as Template[]).find((t) => t.id === id);
  if (!found) throw new Error(`Scout has no template ${id}`);
  return found;
}

/** *id*'s spec, its widgets set to *values*, as a Vega-Lite node writes it. */
function written(id: string, values: Record<string, WidgetValue>): Json {
  const { widgets, source } = template(id);
  const set = widgets.map((w) => (w.name in values ? { ...w, value: values[w.name] } : w));
  const text = fs.readFileSync(path.join(SCOUT, source), "utf-8");
  const { code, problems } = resolveReferences(
    text,
    { widgets: normalizeWidgets(set), inputs: [], shared: [] },
    "json",
    "vega-lite",
  );
  expect(problems).toEqual([]);
  return JSON.parse(code);
}

interface Drawing {
  /** What each mark drew, mark by mark: its kind and each item's place. */
  items: unknown[][];
  /** What vega-lite and vega said: warnings and errors. */
  said: string[];
  view: any;
}

/** *spec* drawn over *rows*, as the dataset `inputs` the charts read. */
async function draw(spec: Json, rows: Json[]): Promise<Drawing> {
  const said: string[] = [];
  const logger: any = {
    level() { return logger; },
    error: (...args: unknown[]) => said.push(args.map(String).join(" ")),
    warn: (...args: unknown[]) => said.push(args.map(String).join(" ")),
    info() {},
    debug() {},
  };
  const compiled = vegaLite.compile({ ...spec, datasets: { inputs: rows } }, { logger }).spec;
  const view = new vega.View(vega.parse(compiled), { renderer: "none" });
  view.logger(logger);
  await view.runAsync();
  const items: unknown[][] = [];
  const round = (value: unknown) => (typeof value === "number" ? Math.round(value * 1e6) / 1e6 : value);
  const walk = (node: any) => {
    if (!node) return;
    if (node.marktype && node.role === "mark") {
      for (const item of node.items ?? []) {
        items.push([
          node.marktype,
          ...["x", "y", "x2", "y2", "width", "height", "startAngle", "endAngle", "size", "text"].map((k) => round(item[k])),
        ]);
      }
    }
    for (const child of node.items ?? []) walk(child);
  };
  walk(view.scenegraph().root);
  return { items, said, view };
}

/** Each scenario's rows, as the repro has them. */
const RAIN = [
  { scenario_name: "A", "rain.mm": 45, cost: 90 },
  { scenario_name: "B", "rain.mm": 61, cost: 170 },
];

const marksOf = (drawing: Drawing, kind: string) => drawing.items.filter((item) => item[0] === kind);

describe("Bars", () => {
  test("draws a bar per scenario for a column with a dot, its field escaped, as for one without", async () => {
    const spec = written("bars", { y: "rain.mm", combine: "mean" });
    expect(spec.encoding.y.field).toBe("rain\\.mm");
    const drawing = await draw(spec, RAIN);
    expect(drawing.said).toEqual([]);
    const bars = marksOf(drawing, "rect");
    expect(bars).toHaveLength(2);
    // Each bar is its scenario's rain, 45 and 61, from the same baseline.
    const [a, b] = bars.map((bar) => bar[6] as number);
    expect(a).toBeGreaterThan(0);
    expect(b / a).toBeCloseTo(61 / 45, 6);
    // And the cost, a column without a dot, draws its two bars alike.
    const cost = await draw(written("bars", { y: "cost", combine: "mean" }), RAIN);
    expect(cost.said).toEqual([]);
    expect(marksOf(cost, "rect")).toHaveLength(2);
  });
});

describe("Table", () => {
  const COLUMNS = ["scenario_name", "rain.mm", "cost"];

  test("folds the columns it lists by their escaped names and orders them by their own", () => {
    const spec = written("table", { columns: COLUMNS });
    const fold = spec.transform.find((step: Json) => "fold" in step).fold;
    expect(fold).toEqual(["scenario_name", "rain\\.mm", "cost"]);
    expect(spec.encoding.x.sort).toEqual(COLUMNS);
  });

  test.each([
    ["the dotted column in the middle", COLUMNS],
    ["the dotted column first", ["rain.mm", "scenario_name", "cost"]],
  ])("shows every cell, its columns in the order it lists them: %s", async (_name, columns) => {
    const drawing = await draw(written("table", { columns }), RAIN);
    expect(drawing.said).toEqual([]);
    expect(drawing.view.scale("x").domain()).toEqual(columns);
    const cells = marksOf(drawing, "text").map((cell) => String(cell[10]));
    expect(cells.sort()).toEqual(["170", "45", "61", "90", "A", "B"]);
  });
});

describe("each of Scout's charts", () => {
  // The columns a chart's widgets name, and the name each takes with a dot or
  // a bracket in it.
  const DOTTED: Record<string, string> = {
    x_n: "x.n", y_n: "y.n", low_n: "low.n", high_n: "high.n", err_n: "err[sd]",
    w_n: "w.n", cat_c: "cat.c", part_c: "part.c", panel_c: "panel.c", group_c: "group[c]",
  };
  const ROWS: Json[] = [];
  for (const [scenario, offset] of [["A", 0], ["B", 3]] as const) {
    ["north", "south", "east"].forEach((cat, i) => {
      for (const x of [1, 2]) {
        ROWS.push({
          scenario: scenario.toLowerCase(), scenario_name: scenario,
          x_n: x, y_n: 10 + offset + i * 2 + x, low_n: 8 + offset + i, high_n: 14 + offset + i, err_n: 1 + i / 2,
          w_n: (i - 1) / 2 + (offset ? 0.25 : 0), cat_c: cat, part_c: x === 1 ? "roofs" : "trees",
          panel_c: x === 1 ? "p1" : "p2", group_c: i % 2 ? "g1" : "g2",
        });
      }
    });
  }
  // Each chart's widgets, the columns they name without a dot.
  const VALUES: Record<string, Record<string, WidgetValue>> = {
    "lines-with-band": { x: "x_n", y: "y_n", low: "low_n", high: "high_n", facet: "panel_c" },
    "curves-by-group": { x: "x_n", y: "y_n", group: "group_c" },
    "bars-with-error-bars": { x: "cat_c", y: "y_n", error: "err_n" },
    "ensemble-strips": { y: "y_n" },
    "stacked-bars-with-totals": { y: "y_n", part: "part_c" },
    donuts: { part: "part_c", value: "y_n", highlight: "roofs" },
    "weighted-matrix": { factor: "cat_c", weight: "w_n" },
    "dots-with-a-range": { category: "cat_c", value: "y_n" },
    bars: { y: "y_n" },
    "grouped-bars": { x: "cat_c", y: "y_n" },
    lines: { x: "x_n", x_type: "quantitative", y: "y_n" },
    points: { x: "x_n", y: "y_n" },
    pie: { value: "y_n" },
    lollipops: { value: "y_n" },
    table: { columns: ["scenario_name", "cat_c", "y_n"] },
  };
  // Vega-Lite's error bar names its bounds after its Y field as it is written,
  // `upper_y\.n`, then reads them as `upper_y.n`: it draws no error bar over a
  // Y column whose name holds a dot, escaped or not. That chart keeps its Y.
  const KEPT: Record<string, string[]> = { "bars-with-error-bars": ["y_n"] };

  const named = (id: string, column: string) => (KEPT[id]?.includes(column) ? column : DOTTED[column] ?? column);
  /** The rows, their columns renamed as chart *id*'s widgets name them. */
  const renamed = (id: string) =>
    ROWS.map((row) => Object.fromEntries(Object.entries(row).map(([column, value]) => [named(id, column), value])));
  const dotted = (id: string): Record<string, WidgetValue> =>
    Object.fromEntries(
      Object.entries(VALUES[id]).map(([widget, value]) => {
        const columns = template(id).widgets.find((w) => w.name === widget)?.type === "text-list";
        if (columns) return [widget, (value as string[]).map((column) => named(id, column))];
        return [widget, typeof value === "string" && value in DOTTED ? named(id, value) : value];
      }),
    );

  /** Every chart Scout ships: its templates that draw with Vega-Lite. */
  const CHARTS: string[] = JSON.parse(fs.readFileSync(path.join(SCOUT, "manifest.json"), "utf-8"))
    .templates.filter((t: Json) => t.grammarId === "vega-lite")
    .map((t: Json) => t.id);

  test.each(CHARTS)("%s draws over columns whose names hold a dot or a bracket", async (id) => {
    expect(Object.keys(VALUES)).toContain(id);
    const plain = await draw(written(id, VALUES[id]), ROWS);
    expect(plain.said).toEqual([]);
    expect(plain.items.length).toBeGreaterThan(0);
    const drawing = await draw(written(id, dotted(id)), renamed(id));
    expect(drawing.said).toEqual([]);
    expect(drawing.items).toEqual(plain.items);
  });
});
