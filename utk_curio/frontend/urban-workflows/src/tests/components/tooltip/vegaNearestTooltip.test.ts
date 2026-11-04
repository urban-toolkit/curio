/**
 * @jest-environment node
 */
/**
 * Where the nearest mark's tooltip (components/tooltip/vegaTooltip.ts) finds
 * one, in the scenegraph Vega builds from a Vega-Lite spec. Vega answers a
 * line only within its stroke's width of one of its points, whether the mark
 * says `"tooltip": true` or an encoding names its fields; between them, or a
 * few pixels off, the nearest mark's tooltip answers.
 *
 * Each chart is 450 x 200 with no padding and no axes, its x scale 0 to 9 and
 * its y scale 0 to 100, so a value's place is known: x at 50 px a unit, y at
 * 200 less 2 px a unit. The specs are compiled by the vega-lite the app
 * bundles and run by its vega with no renderer. It runs in Node's environment,
 * as crownHeightsPlotLegend.test.ts does: vega-lite's build reads
 * `structuredClone`, which jsdom's window does not have.
 */
import * as path from "path";
import { nearestVegaTooltip, VEGA_TOOLTIP_REACH_PX, type VegaSceneMark } from "../../../components/tooltip/vegaTooltip";

// vega-lite's build asks for vega, whose package entry is an ES module, which
// Jest does not load: vega's UMD build is the same vega as CommonJS.
jest.mock("vega", () => require(require("path").resolve(__dirname, "../../../../node_modules/vega/build/vega.js")), {
  virtual: true,
});

const NODE_MODULES = path.resolve(__dirname, "../../../../node_modules");
const vegaLite = require(path.join(NODE_MODULES, "vega-lite/build/vega-lite.min.js"));
const vega = require("vega");

const REACH = VEGA_TOOLTIP_REACH_PX;

/** Four points: (0, 10), (3, 70), (6, 30) and (9, 60); on the chart, (0, 180), (150, 60), (300, 140), (450, 80). */
const ROWS = [
  { x: 0, y: 10 },
  { x: 3, y: 70 },
  { x: 6, y: 30 },
  { x: 9, y: 60 },
];
const CHART = {
  $schema: "https://vega.github.io/schema/vega-lite/v5.json",
  width: 450,
  height: 200,
  padding: 0,
  autosize: "none",
  data: { values: ROWS },
};
const X = { field: "x", type: "quantitative", axis: null, scale: { domain: [0, 9] } };
const Y = { field: "y", type: "quantitative", axis: null, scale: { domain: [0, 100] } };

/** The scenegraph Vega builds for the Vega-Lite *spec*. */
async function sceneOf(spec: object): Promise<VegaSceneMark> {
  const view = new vega.View(vega.parse(vegaLite.compile({ ...CHART, ...spec }).spec), { renderer: "none" });
  await view.runAsync();
  return view.scenegraph().root as VegaSceneMark;
}

/** The tooltip nearest (x, y) in *scene*, within *reach*, or null. */
function tooltipAt(scene: VegaSceneMark, x: number, y: number, reach = REACH): unknown {
  return nearestVegaTooltip(scene, x, y, reach)?.tooltip ?? null;
}

// `"tooltip": true` writes each field's value as Vega-Lite formats it, as text.
describe("the nearest mark's tooltip, in a scenegraph Vega built", () => {
  test("on a line saying tooltip: true, between its points, the nearer point's", async () => {
    const scene = await sceneOf({ mark: { type: "line", tooltip: true }, encoding: { x: X, y: Y } });
    // On the line from (0, 180) to (150, 60), 40% of the way: the first point is nearer.
    expect(tooltipAt(scene, 60, 132)).toEqual({ x: "0", y: "10" });
    // 70% of the way: the second.
    expect(tooltipAt(scene, 105, 96)).toEqual({ x: "3", y: "70" });
    // 6 px below that first place, about 5 px from the line.
    expect(tooltipAt(scene, 60, 138)).toEqual({ x: "0", y: "10" });
  });

  test("on a line whose encoding names the tooltip's fields, the same", async () => {
    const scene = await sceneOf({ mark: "line", encoding: { x: X, y: Y, tooltip: [{ field: "y" }] } });
    expect(tooltipAt(scene, 60, 132)).toEqual({ y: 10 });
    // On the line from (150, 60) to (300, 140), 30% of the way.
    expect(tooltipAt(scene, 195, 84)).toEqual({ y: 70 });
  });

  test("none farther than the reach", async () => {
    const scene = await sceneOf({ mark: { type: "line", tooltip: true }, encoding: { x: X, y: Y } });
    // 20 px below the line's 40% place: about 16 px from the line.
    expect(tooltipAt(scene, 60, 152)).toBeNull();
    expect(tooltipAt(scene, 60, 152, 2 * REACH)).toEqual({ x: "0", y: "10" });
  });

  test("none from a mark with no tooltip", async () => {
    const scene = await sceneOf({ mark: "line", encoding: { x: X, y: Y } });
    expect(tooltipAt(scene, 60, 132)).toBeNull();
  });

  test("near a rule, and near a bar's edge, theirs", async () => {
    const rules = await sceneOf({ mark: { type: "rule", tooltip: true }, encoding: { x: X } });
    // The rule at x = 3 runs the chart's height at 150 px.
    expect(tooltipAt(rules, 155, 100)).toEqual({ x: "3" });
    const bars = await sceneOf({ mark: { type: "bar", tooltip: true, width: 20 }, encoding: { x: X, y: Y } });
    // The bar at x = 3 spans 140 to 160 px, from 60 px down to the bottom.
    expect(tooltipAt(bars, 165, 150)).toEqual({ x: "3", y: "70" });
    expect(tooltipAt(bars, 175, 150)).toBeNull();
  });
});
