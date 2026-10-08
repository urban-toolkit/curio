/**
 * A map layer that names a scenario wears that scenario's color, and the map
 * gets one legend naming each scenario it draws.
 */
import {
  SCENARIO_LEGEND_ATTR,
  colorScenarioLayers,
  scenarioLayers,
} from "../../../adapters/node/autkScenarioLayers";

const scenarios = [
  { id: "avoid-rain", name: "Avoid rain", color: "#2a9d8f", nodes: [] },
  { id: "avoid-wind", name: "Avoid wind", color: "#e76f51", nodes: [] },
] as any[];

const spec = {
  map: {
    layerRefs: [
      { dataRef: "input_0" },
      { dataRef: "input_1", scenario: "avoid-rain" },
      { dataRef: "input_2", scenario: "avoid-wind" },
      { dataRef: "input_3", scenario: "gone" },
    ],
  },
};

/** autk-map as colorScenarioLayers uses it: one map for every dataRef. */
function fakeGrammar() {
  const host = document.createElement("div");
  const canvas = document.createElement("canvas");
  host.appendChild(canvas);
  const map = { canvas, updateRenderInfo: jest.fn() };
  const registry = new Map(["input_0", "input_1", "input_2", "input_3"].map((id) => [id, map]));
  return { grammar: { _mapRegistry: registry }, map, host };
}

describe("scenarioLayers", () => {
  test("names each layer by its scenario, in the document's order, and skips the rest", () => {
    expect(scenarioLayers(spec, scenarios)).toEqual([[
      { dataRef: "input_1", color: "#2a9d8f", label: "Avoid rain" },
      { dataRef: "input_2", color: "#e76f51", label: "Avoid wind" },
    ]]);
    expect(scenarioLayers({ plot: {} }, scenarios)).toEqual([]);
  });
});

describe("colorScenarioLayers", () => {
  test("each layer is drawn in its scenario's color, not color-mapped, with a darker outline", () => {
    const { grammar, map } = fakeGrammar();
    colorScenarioLayers(grammar, spec, scenarios);
    expect(map.updateRenderInfo).toHaveBeenCalledWith("input_1", {
      isColorMap: false, color: { r: 0x2a, g: 0x9d, b: 0x8f, alpha: 1 },
      strokeColor: { r: 27, g: 102, b: 93, alpha: 1 },
    });
    expect(map.updateRenderInfo).toHaveBeenCalledWith("input_2", {
      isColorMap: false, color: { r: 0xe7, g: 0x6f, b: 0x51, alpha: 1 },
      strokeColor: { r: 150, g: 72, b: 53, alpha: 1 },
    });
    expect(map.updateRenderInfo).toHaveBeenCalledTimes(2);
  });

  test("the map gets one legend, a swatch and a name per scenario, replaced on a redraw", () => {
    const { grammar, host } = fakeGrammar();
    colorScenarioLayers(grammar, spec, scenarios);
    colorScenarioLayers(grammar, spec, [{ ...scenarios[0], color: "#3567c7", name: "Dry" }, scenarios[1]]);
    const legends = host.querySelectorAll(`[${SCENARIO_LEGEND_ATTR}]`);
    expect(legends).toHaveLength(1);
    const rows = Array.from(legends[0].children) as HTMLElement[];
    expect(rows.map((row) => row.textContent)).toEqual(["Dry", "Avoid wind"]);
    expect((rows[0].firstElementChild as HTMLElement).style.backgroundColor).toBe("rgb(53, 103, 199)");
  });

  test("a layer with a color of its own wears it, with its outline, and the legend names it by its label", () => {
    const { grammar, map, host } = fakeGrammar();
    const routes = {
      map: {
        layerRefs: [
          { dataRef: "input_0" },
          { dataRef: "input_1", color: "#90CAF9", stroke: "#42A5F5", label: "Fastest route" },
          { dataRef: "input_2", color: "#00ACC1" },
          { dataRef: "input_3", color: "not a color" },
        ],
      },
    };
    colorScenarioLayers(grammar, routes, scenarios);
    expect(map.updateRenderInfo).toHaveBeenCalledWith("input_1", {
      isColorMap: false, color: { r: 0x90, g: 0xca, b: 0xf9, alpha: 1 },
      strokeColor: { r: 0x42, g: 0xa5, b: 0xf5, alpha: 1 },
    });
    // No stroke: a darker shade of its color.
    expect(map.updateRenderInfo).toHaveBeenCalledWith("input_2", {
      isColorMap: false, color: { r: 0x00, g: 0xac, b: 0xc1, alpha: 1 },
      strokeColor: { r: 0, g: 112, b: 125, alpha: 1 },
    });
    expect(map.updateRenderInfo).toHaveBeenCalledTimes(2);
    const rows = Array.from(host.querySelector(`[${SCENARIO_LEGEND_ATTR}]`)!.children) as HTMLElement[];
    expect(rows.map((row) => row.textContent)).toEqual(["Fastest route", "input_2"]);
    expect((rows[0].firstElementChild as HTMLElement).style.border).toBe("2px solid rgb(66, 165, 245)");
  });

  test("a map with no scenario layer gets no legend, and a missing registry is no error", () => {
    const { grammar, host } = fakeGrammar();
    colorScenarioLayers(grammar, { map: { layerRefs: [{ dataRef: "input_0" }] } }, scenarios);
    expect(host.querySelector(`[${SCENARIO_LEGEND_ATTR}]`)).toBeNull();
    expect(() => colorScenarioLayers({}, spec, scenarios)).not.toThrow();
  });
});
