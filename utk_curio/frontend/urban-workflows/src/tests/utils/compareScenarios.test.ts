/**
 * The Compare Scenarios node (#662), read from the live graph: each input
 * labelled by the scenario its node belongs to, the levers that differ paired
 * by lineage, and a warning when the scenarios read different context.
 */
import {
  compareInputs,
  labelsNeedWriting,
  labelWarnings,
  layersToPick,
  listOf,
} from "../../utils/compare/compareInputs";
import { NO_SCENARIO_COLOR, normalizeCompareSettings, sameLabels } from "../../utils/compare/compareSettings";
import {
  changedLines,
  comparedScenarios,
  contextWarnings,
  lineageKeys,
  pairLevers,
  whatDiffers,
} from "../../utils/compare/whatDiffers";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

jest.mock("../../utils/palettePackageFactoryDraft", () => ({
  resolveNodeDisplayLabel: (data: any) => data.title ?? data.nodeId,
}));

const COMPARE = "compare";

function node(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "__curioUniversalNode",
    data: { nodeId: id, nodeType: "curio.builtin/computation-analysis@1", code: "return arg", ...extra },
  } as any;
}

const parameter = (id: string, name: string, value: number) =>
  node(id, {
    nodeType: "curio.builtin/parameter@1",
    code: undefined,
    title: `Parameter ${name}`,
    widgets: [{ name, type: "number", default: 1, value }],
  });

function edge(source: string, target: string, targetHandle = "in") {
  return { id: `${source}-${target}-${targetHandle}`, source, target, sourceHandle: "out", targetHandle } as any;
}

const scenario = (id: string, name: string, color: string, nodes: string[]): Scenario => ({ id, name, color, nodes });

const factor = (value: number) => [{ name: "factor", type: "number", default: 1, value }];

/**
 * load -> scale -> chart in Baseline; load -> scale copy -> chart copy in
 * Twice as tall, each copy naming its original. Both charts feed the compare
 * node, on circles 0 and 1.
 */
function twoScenarios() {
  const nodes = [
    node("load", { title: "Loader" }),
    node("scale", { title: "Scale", widgets: factor(1), code: "gdf = arg.copy()\ngdf['h'] = gdf['h'] * [!! factor !!]\nreturn gdf" }),
    node("chart", { title: "Sunlight" }),
    node("scale-2", {
      title: "Scale",
      widgets: factor(2),
      copiedFrom: ["scale"],
      code: "gdf = arg.copy()\ngdf['h'] = gdf['h'] * [!! factor !!]\ngdf = gdf[gdf['h'] > 0]\nreturn gdf",
    }),
    node("chart-2", { title: "Sunlight", copiedFrom: ["chart"] }),
    node(COMPARE, { nodeType: "curio.builtin/compare-scenarios@1", title: "Compare" }),
  ];
  const edges = [
    edge("load", "scale"),
    edge("scale", "chart"),
    edge("load", "scale-2"),
    edge("scale-2", "chart-2"),
    edge("chart", COMPARE, "in"),
    edge("chart-2", COMPARE, "in_1"),
  ];
  const scenarios = [
    scenario("s-base", "Baseline", "#2a9d8f", ["scale", "chart"]),
    scenario("s-tall", "Twice as tall", "#e76f51", ["scale-2", "chart-2"]),
  ];
  return { nodes, edges, scenarios };
}

describe("compareInputs", () => {
  test("labels each circle by the scenario its node belongs to, in circle order", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    // Listed out of order: the circle decides.
    const inputs = compareInputs(COMPARE, nodes, [...edges].reverse(), scenarios);
    expect(inputs.map((input) => [input.slot, input.source, input.label])).toEqual([
      [0, "chart", { scenario: "s-base", name: "Baseline", color: "#2a9d8f" }],
      [1, "chart-2", { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" }],
    ]);
  });

  test("an input whose node is in no scenario carries the node's name and a neutral color", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const inputs = compareInputs(COMPARE, nodes, [...edges, edge("load", COMPARE, "in_2")], scenarios);
    expect(inputs[2]).toEqual({ slot: 2, source: "load", scenario: null, label: { name: "Loader", color: NO_SCENARIO_COLOR } });
    expect(labelWarnings(inputs)).toEqual([
      "Input 2 comes from Loader, which is in no scenario: its rows carry the node's name, and What differs leaves it out.",
    ]);
  });

  test("an interaction edge is not an input, and a member deleted since the save labels nothing", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const interaction = { id: "i", source: "chart", target: COMPARE, sourceHandle: "in/out", targetHandle: "in/out" } as any;
    const live = nodes.filter((n) => n.id !== "chart-2");
    const inputs = compareInputs(COMPARE, live, [...edges, interaction], scenarios);
    expect(inputs.map((input) => input.slot)).toEqual([0, 1]);
    expect(inputs[1].scenario).toBeNull();
  });

  test("inputs from one scenario are said to share its name", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const inputs = compareInputs(COMPARE, nodes, [...edges, edge("scale", COMPARE, "in_2")], scenarios);
    expect(labelWarnings(inputs)).toEqual(["Inputs 0 and 2 come from one scenario, Baseline: their rows carry the same name."]);
  });

  test("listOf joins names the way a sentence does", () => {
    expect([listOf([]), listOf(["a"]), listOf(["a", "b"]), listOf(["a", "b", "c"])]).toEqual(["", "a", "a and b", "a, b and c"]);
  });
});

describe("labelsNeedWriting", () => {
  const { nodes, edges, scenarios } = twoScenarios();
  const inputs = compareInputs(COMPARE, nodes, edges, scenarios);
  const stored = inputs.map((input) => input.label);

  test("labels that say what the graph says are kept", () => {
    expect(labelsNeedWriting(stored, inputs, true)).toBe(false);
    expect(labelsNeedWriting(undefined, [], true)).toBe(false);
  });

  test("a new input, or a renamed scenario, writes them again", () => {
    expect(labelsNeedWriting(stored.slice(0, 1), inputs, true)).toBe(true);
    const renamed = compareInputs(COMPARE, nodes, edges, [{ ...scenarios[0], name: "Base" }, scenarios[1]]);
    expect(labelsNeedWriting(stored, renamed, true)).toBe(true);
  });

  test("a load that has added the nodes but not yet the edges writes nothing", () => {
    const noEdges = compareInputs(COMPARE, nodes, [], scenarios);
    expect(noEdges).toEqual([]);
    expect(labelsNeedWriting(stored, noEdges, false)).toBe(false);
    // The last edge into it deleted, while the dataflow keeps others.
    expect(labelsNeedWriting(stored, noEdges, true)).toBe(true);
  });
});

describe("normalizeCompareSettings", () => {
  test("keeps well-formed labels and chart settings, and nothing else", () => {
    expect(
      normalizeCompareSettings({
        inputs: [{ scenario: "s1", name: "Baseline", color: "#2a9d8f", extra: 1 }, { name: "Loader", color: "#8a8f98" }],
        chart: { preset: "bar", x: "", y: "sunlight", aggregate: "median", size: 3 },
        other: true,
      }),
    ).toEqual({
      inputs: [{ scenario: "s1", name: "Baseline", color: "#2a9d8f" }, { name: "Loader", color: "#8a8f98" }],
      chart: { preset: "bar", y: "sunlight", aggregate: "median" },
    });
  });

  test("drops every label when one is not well formed: one less would shift the others onto other circles", () => {
    expect(
      normalizeCompareSettings({ inputs: [{ name: "Baseline", color: "#2a9d8f" }, { name: "Tall", color: "red" }] }),
    ).toBeUndefined();
  });

  test("is undefined when nothing is left, so nothing is written", () => {
    expect(normalizeCompareSettings(undefined)).toBeUndefined();
    expect(normalizeCompareSettings({ inputs: [], chart: { preset: "radar" } })).toBeUndefined();
  });

  test("sameLabels compares circle by circle", () => {
    const a = [{ scenario: "s1", name: "B", color: "#000000" }];
    expect(sameLabels(a, [{ ...a[0] }])).toBe(true);
    expect(sameLabels(a, [{ name: "B", color: "#000000" }])).toBe(false);
    expect(sameLabels(undefined, [])).toBe(true);
  });

  test("keeps the layer it reads from an Autark node's several, when it names one", () => {
    expect(normalizeCompareSettings({ layer: "table_osm_roads" })).toEqual({ layer: "table_osm_roads" });
    expect(normalizeCompareSettings({ layer: "" })).toBeUndefined();
    expect(normalizeCompareSettings({ layer: 3 })).toBeUndefined();
  });
});

describe("layersToPick", () => {
  const roads = ["table_osm_surface", "table_osm_buildings", "table_osm_roads"];

  test("offers the layers every input of several layers has, in the first one's order", () => {
    expect(layersToPick([roads, ["table_osm_roads", "table_osm_buildings"]])).toEqual(["table_osm_buildings", "table_osm_roads"]);
  });

  test("an input of one table offers nothing and takes nothing away", () => {
    expect(layersToPick([["only"], [null]])).toEqual([]);
    expect(layersToPick([roads, ["only"]])).toEqual(roads);
  });

  test("offers nothing before the inputs are read", () => {
    expect(layersToPick([])).toEqual([]);
  });
});

describe("pairing levers by lineage", () => {
  test("a node and its copy, a copy of a copy, and two copies of one original pair", () => {
    const original = node("o");
    const copy = node("c", { copiedFrom: ["o"] });
    const copyOfCopy = node("cc", { copiedFrom: ["o", "c"] });
    const sibling = node("s", { copiedFrom: ["o"] });
    expect(lineageKeys(copyOfCopy)).toEqual(["cc", "o", "c"]);
    const pairs = pairLevers([
      { scenarioId: "a", levers: [copy] },
      { scenarioId: "b", levers: [copyOfCopy] },
      { scenarioId: "c", levers: [sibling] },
    ]);
    expect(pairs.map((members) => Object.fromEntries(members))).toEqual([{ a: ["c"], b: ["cc"], c: ["s"] }]);
    expect(pairLevers([{ scenarioId: "a", levers: [original] }, { scenarioId: "b", levers: [node("x")] }]).length).toBe(2);
  });
});

describe("whatDiffers", () => {
  test("lists the widget values and the code lines that differ, by lever", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const compared = comparedScenarios(compareInputs(COMPARE, nodes, edges, scenarios));
    expect(compared.map((c) => [c.slot, c.scenario.id])).toEqual([[0, "s-base"], [1, "s-tall"]]);
    const differs = whatDiffers(compared, nodes, edges);
    expect(differs.differences).toEqual([
      {
        key: "scale",
        label: "Scale",
        widgets: [{ name: "factor", values: [{ scenarioId: "s-base", value: 1 }, { scenarioId: "s-tall", value: 2 }] }],
        code: [{ scenarioId: "s-tall", removed: [], added: ["gdf = gdf[gdf['h'] > 0]"] }],
      },
    ]);
    // The two charts are one lever, alike.
    expect(differs.same).toBe(1);
  });

  test("a lever with no partner is listed as only in the scenarios that have it", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const extra = node("filter", { title: "Filter" });
    const tall = { ...scenarios[1], nodes: [...scenarios[1].nodes, "filter"] };
    const compared = comparedScenarios(compareInputs(COMPARE, [...nodes, extra], edges, [scenarios[0], tall]));
    const only = whatDiffers(compared, [...nodes, extra], edges).differences.find((d) => d.key === "filter");
    expect(only).toEqual({ key: "filter", label: "Filter", onlyIn: ["s-tall"], widgets: [], code: [] });
  });

  test("levers built apart, with no lineage between them, do not pair", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const unlinked = nodes.map((n) => (n.id === "scale-2" ? node("scale-2", { ...n.data, copiedFrom: undefined }) : n));
    const compared = comparedScenarios(compareInputs(COMPARE, unlinked, edges, scenarios));
    const onlyIn = whatDiffers(compared, unlinked, edges).differences.map((d) => [d.key, d.onlyIn]);
    expect(onlyIn).toEqual([["scale", ["s-base"]], ["scale-2", ["s-tall"]]]);
  });

  test("an input in no scenario is left out of the comparison", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const compared = comparedScenarios(compareInputs(COMPARE, nodes, [...edges, edge("load", COMPARE, "in_2")], scenarios));
    expect(compared.map((c) => c.scenario.id)).toEqual(["s-base", "s-tall"]);
  });
});

describe("changedLines", () => {
  test("keeps the lines both share and lists the rest in order", () => {
    expect(changedLines("a\nb\nc", "a\nB\nc\nd")).toEqual({ removed: ["b"], added: ["B", "d"] });
    expect(changedLines("same\r\nlines", "same\nlines")).toEqual({ removed: [], added: [] });
  });
});

describe("contextWarnings", () => {
  test("scenarios that read the same context say nothing", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const compared = comparedScenarios(compareInputs(COMPARE, nodes, edges, scenarios));
    expect(contextWarnings(compared, nodes, edges)).toEqual([]);
  });

  test("a scenario that reads another loader is named, with the inputs, and so is what only the other reads", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const second = node("load-2", { title: "Loader 2020" });
    const rewired = [...edges.filter((e) => !(e.source === "load" && e.target === "scale-2")), edge("load-2", "scale-2")];
    const all = [...nodes, second];
    const compared = comparedScenarios(compareInputs(COMPARE, all, rewired, scenarios));
    expect(contextWarnings(compared, all, rewired)).toEqual([
      "Input 1 (Twice as tall) and input 0 (Baseline) read different context: only input 1 reads Loader 2020; only input 0 reads Loader.",
    ]);
  });

  test("a Parameter node one scenario's code names is context too", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const all = [
      ...nodes.map((n) => (n.id === "scale-2" ? node("scale-2", { ...n.data, code: "return arg * [!! @season !!]" }) : n)),
      parameter("season", "season", 2),
    ];
    const compared = comparedScenarios(compareInputs(COMPARE, all, edges, scenarios));
    expect(contextWarnings(compared, all, edges)).toEqual([
      "Input 1 (Twice as tall) and input 0 (Baseline) read different context: only input 1 reads Parameter season.",
    ]);
  });

  test("two context nodes of one name are told apart by their ids", () => {
    const { nodes, edges, scenarios } = twoScenarios();
    const twin = node("lzzz", { title: "Loader" });
    const rewired = [...edges.filter((e) => !(e.source === "load" && e.target === "scale-2")), edge("lzzz", "scale-2")];
    const all = [...nodes, twin];
    const compared = comparedScenarios(compareInputs(COMPARE, all, rewired, scenarios));
    expect(contextWarnings(compared, all, rewired)[0]).toContain("only input 1 reads Loader (lzzz); only input 0 reads Loader (load)");
  });
});
