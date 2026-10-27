/**
 * @jest-environment node
 */
/**
 * The Crown Heights example's two plots (#1179) compile with no conflicting
 * legend. Each draws a line per scenario whose color and width both read
 * `scenario_name`, and Vega-Lite draws the two channels' legends as one. A
 * width that writes `"legend": null` beside a color that writes a legend turns
 * that one legend off and on at once: Vega-Lite keeps it, and says
 * `Conflicting legend property "disable" (false and true). Using false.` in
 * the console, as the example's dashboard did eight times.
 *
 * Each plot is its node's text with its chips resolved as the editor resolves
 * them (utils/references/codeReferences), over the boxes its inputs come from,
 * compiled by the vega-lite the app bundles, with a logger of the test's own
 * hearing what it says. It runs in Node's environment, as
 * scoutDottedColumns.test.ts does: vega-lite's build reads `structuredClone`,
 * which jsdom's window does not have.
 */
import * as fs from "fs";
import * as path from "path";
import { VEGA_LITE, resolveReferences } from "../../../utils/references/codeReferences";
import { inputScopeFor } from "../../../utils/references/inputScope";
import { inputScenarios } from "../../../utils/scenarios/inputScenarios";
import { normalizeScenarios } from "../../../utils/scenarios/scenarioModel";
import { normalizeWidgets } from "../../../utils/widgets/widgetModel";
import { REPO_ROOT } from "../../_support/workflowPaths";

// vega-lite's build asks for vega, whose package entry is an ES module, which
// Jest does not load: vega's UMD build is the same vega as CommonJS.
jest.mock("vega", () => require(require("path").resolve(__dirname, "../../../../node_modules/vega/build/vega.js")), {
  virtual: true,
});

const NODE_MODULES = path.resolve(__dirname, "../../../../node_modules");
const vegaLite = require(path.join(NODE_MODULES, "vega-lite/build/vega-lite.min.js"));

const EXAMPLE = path.join(REPO_ROOT, "docs", "examples", "dataflows", "crown-heights-1550-bedford-shadow.json");
const VEGA_LITE_NODE = "curio.builtin/vis-vega";
const CONFLICT = /^Conflicting /;

type Plot = { name: string; spec: any; problems: unknown[] };

/** Each Vega-Lite node of the example, its chips resolved as the canvas resolves them. */
function plots(): Plot[] {
  const flow = JSON.parse(fs.readFileSync(EXAMPLE, "utf-8")).dataflow;
  const nodes = flow.nodes as any[];
  const edges = flow.edges as any[];
  // As the canvas holds them: a node's title is what an input's label names.
  const canvasNodes = nodes.map((node) => ({ id: node.id, type: node.type, data: { title: node.title, nodeType: node.type } }));
  const scenarios = normalizeScenarios(flow.scenarios, nodes.map((node) => node.id));
  return nodes
    .filter((node) => node.type === VEGA_LITE_NODE)
    .map((node) => {
      const labels = new Map(
        inputScenarios(node.id, canvasNodes, edges, scenarios).map((input) => [input.slot, input.label]),
      );
      const inputs = inputScopeFor(node.id, edges, canvasNodes, () => undefined, (data) => data?.title ?? null, () => undefined)
        .map((input) => (labels.has(input.slot) ? { ...input, scenario: labels.get(input.slot) } : input));
      const scope = { widgets: normalizeWidgets(node.metadata?.widgets), inputs };
      const { code, problems } = resolveReferences(node.content, scope, "json", VEGA_LITE);
      return { name: `${node.title} (${node.id})`, spec: problems.length ? null : JSON.parse(code), problems };
    });
}

/** The unit of *spec* that draws the lines: the one whose width reads a field. */
const lines = (spec: any) => [spec, ...(spec.layer ?? [])].find((unit) => unit.encoding?.strokeWidth);

/** *spec* compiled to Vega, and every message vega-lite logs while it compiles it. */
function compiled(spec: unknown): { vega: any; said: string[] } {
  const said: string[] = [];
  const logger: any = {
    level: () => logger,
    error: (...args: unknown[]) => { said.push(args.join(" ")); return logger; },
    warn: (...args: unknown[]) => { said.push(args.join(" ")); return logger; },
    info: () => logger,
    debug: () => logger,
  };
  const vega = vegaLite.compile(spec, { logger }).spec;
  return { vega, said };
}

const PLOTS = plots();

test("the example has its two plots, each a line per scenario whose color and width read scenario_name", () => {
  expect(PLOTS).toHaveLength(2);
  for (const plot of PLOTS) {
    expect(plot.problems).toEqual([]);
    const { encoding } = lines(plot.spec);
    expect([encoding.color.field, encoding.strokeWidth.field]).toEqual(["scenario_name", "scenario_name"]);
  }
});

test.each(PLOTS.map((plot) => [plot.name, plot] as const))(
  "%s compiles with no conflict, to one legend of both its colors and its widths",
  (_name, plot) => {
    const { vega, said } = compiled(plot.spec);
    expect(said.filter((message) => CONFLICT.test(message))).toEqual([]);
    expect(vega.legends).toHaveLength(1);
    expect(vega.legends[0]).toMatchObject({ stroke: "color", strokeWidth: "strokeWidth" });
  },
);

test("a width that turns its legend off is heard, and the plot compiles to the same Vega", () => {
  for (const plot of PLOTS) {
    const spec = JSON.parse(JSON.stringify(plot.spec));
    lines(spec).encoding.strokeWidth.legend = null;
    const { vega, said } = compiled(spec);
    expect(said.filter((message) => CONFLICT.test(message))).toEqual([
      'Conflicting legend property "disable" (false and true). Using false.',
    ]);
    // Vega-Lite keeps the legend, so the plot drew then what it draws now.
    expect(vega).toEqual(compiled(plot.spec).vega);
  }
});
