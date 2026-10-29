/**
 * Scenarios of one set dragged in from the Scenario Catalog (#662), as the
 * canvas builds them: fresh ids naming their originals, one Data Loading node
 * per context input wired where the context was, shared once, the set's
 * shared outcomes that came wired to the copies, saved outputs sent to the
 * copies that make them, and a new scenario set, named after theirs with
 * "(copy)", with everything collapsed.
 */
import { buildDatasetLoaderNodeOptions } from "../../services/datasetCatalog/datasetApplication";
import type { ScenarioCopyPlan } from "../../services/scenarioCatalog/scenarioCatalogTypes";
import type { SpecNode } from "../../utils/scenarios/duplicateSelection";
import type { Scenario, ScenarioSet } from "../../utils/scenarios/scenarioModel";
import { dropGraph, loaderNodes, planScenarioDrop, type ScenarioDrop } from "../../utils/scenarios/scenarioDrop";

const AT = { x: 50, y: 70 };

function counter() {
  let n = 0;
  return () => `new-${++n}`;
}

const TALL = { id: "s1", name: "Twice as tall", color: "#e86a3c", description: "Heights doubled" };

function plan(overrides: Partial<ScenarioCopyPlan> = {}): ScenarioCopyPlan {
  return {
    scenario: TALL,
    scenarios: [{ ...TALL, levers: ["scale", "map"], context: ["pool"], outcomes: [] }],
    set: { id: "heights", name: "Building heights" },
    shared: [],
    project: { id: "p-src", name: "Shadows" },
    levers: ["scale", "map"],
    context: [
      { nodeId: "pool", label: "Data pool", source: { nodeId: "load", copiedFrom: [], datasetId: "computed.p-src.load" } },
    ],
    outcomes: [{ nodeId: "map", label: "Autk grammar", sources: ["scale"] }],
    dataflow: {
      nodes: [
        { id: "scale", type: "curio.builtin/computation-analysis@1", x: 600, y: 100, content: "return input_0", metadata: { copiedFrom: ["first"] } },
        { id: "map", type: "curio.builtin/autk-grammar@1", x: 1200, y: 100, content: "{}" },
      ],
      edges: [
        { id: "e1", source: "pool", target: "scale", sourceHandle: "out", targetHandle: "in" },
        { id: "e2", source: "scale", target: "map", sourceHandle: "out", targetHandle: "in" },
      ],
    },
    packages: [],
    toRun: [],
    problems: [],
    ...overrides,
  };
}

/** The plan with a second context node: Season, a value node (a Python node
 *  that returns its widget's value) wired into the scale lever's second circle. */
function withSeason(): ScenarioCopyPlan {
  const base = plan();
  return {
    ...base,
    context: [
      ...base.context,
      { nodeId: "season", label: "Season", source: { nodeId: "season", copiedFrom: [], datasetId: "computed.p-src.season" } },
    ],
    dataflow: {
      ...base.dataflow,
      edges: [
        ...base.dataflow.edges,
        { id: "e3", source: "season", target: "scale", sourceHandle: "out", targetHandle: "in_1" },
      ],
    },
  };
}

/** Two scenarios of a set: each scales the pooled heights its own way, and a
 *  compare step reads both, feeding a chart. */
function twoScenarios(): ScenarioCopyPlan {
  const node = (id: string, x: number, y: number) => ({
    id, type: "curio.builtin/computation-analysis@1", x, y, content: "return input_0",
  });
  return plan({
    scenarios: [
      { ...TALL, levers: ["scale"], context: ["pool"], outcomes: ["compare", "chart"] },
      { id: "s2", name: "Real heights", color: "#2a9d8f", description: "", levers: ["real"], context: ["pool"], outcomes: ["compare", "chart"] },
    ],
    levers: ["scale", "real"],
    shared: [
      { nodeId: "compare", label: "Compare", scenarios: ["s1", "s2"], sources: ["compare"] },
      { nodeId: "chart", label: "Vis Vega", scenarios: ["s1", "s2"], sources: ["compare"] },
    ],
    outcomes: [
      { nodeId: "scale", label: "Scale", sources: ["scale"] },
      { nodeId: "real", label: "Real", sources: ["real"] },
    ],
    dataflow: {
      nodes: [node("scale", 600, 100), node("real", 600, 500), node("compare", 1200, 300), node("chart", 1800, 300)],
      edges: [
        { id: "e1", source: "pool", target: "scale", sourceHandle: "out", targetHandle: "in" },
        { id: "e2", source: "pool", target: "real", sourceHandle: "out", targetHandle: "in" },
        { id: "e3", source: "scale", target: "compare", sourceHandle: "out", targetHandle: "in_0" },
        { id: "e4", source: "real", target: "compare", sourceHandle: "out", targetHandle: "in_1" },
        { id: "e5", source: "compare", target: "chart", sourceHandle: "out", targetHandle: "in" },
      ],
    },
  });
}

function drop(
  p: ScenarioCopyPlan,
  live: { nodes: SpecNode[]; edges: any[] } = { nodes: [], edges: [] },
  scenarios: Scenario[] = [],
  sets: ScenarioSet[] = [],
): ScenarioDrop {
  const built = planScenarioDrop(p, live, scenarios, sets, { newId: counter(), at: AT });
  if ("error" in built) throw new Error(built.error);
  return built;
}

const copyOf = (d: ScenarioDrop, original: string) =>
  d.nodes.find((n) => (n.metadata?.copiedFrom as string[] | undefined)?.at(-1) === original)!;

describe("planScenarioDrop", () => {
  test("the levers are copied with fresh ids, each naming its original, placed at the drop", () => {
    const d = drop(plan());
    const scale = copyOf(d, "scale");
    const map = copyOf(d, "map");
    expect(new Set([scale.id, map.id]).size).toBe(2);
    expect([scale.id, map.id]).not.toContain("scale");
    expect(scale.metadata?.copiedFrom).toEqual(["first", "scale"]);
    expect(map.metadata?.copiedFrom).toEqual(["map"]);
    // The levers' top-left corner lands where the scenario was dropped.
    expect([scale.x, scale.y, map.x, map.y]).toEqual([50, 70, 650, 70]);
    expect(d.edges).toContainEqual(expect.objectContaining({ source: scale.id, target: map.id, targetHandle: "in" }));
  });

  test("each context input arrives as one Data Loading node, wired where the context was", () => {
    const d = drop(plan());
    expect(d.loaders).toHaveLength(1);
    const [loader] = d.loaders;
    expect(loader.source).toBe("load");
    expect(loader.copiedFrom).toEqual(["load"]);
    expect(loader.position.x).toBeLessThan(AT.x);
    const scale = copyOf(d, "scale");
    expect(d.edges).toContainEqual(expect.objectContaining({ source: loader.id, sourceHandle: "out", target: scale.id }));
    expect(d.edges.some((e) => e.source === "pool" || e.target === "pool")).toBe(false);
  });

  test("the server is told which saved output each copy gets: the context's and the outcomes'", () => {
    const d = drop(plan());
    expect(d.outputs).toEqual([
      { source: "load", node: d.loaders[0].id },
      { source: "scale", node: copyOf(d, "scale").id },
    ]);
  });

  test("even one scenario arrives in a new set, collapsed where it was dropped, naming where it came from", () => {
    const d = drop(plan());
    expect(d.set).toEqual({
      id: expect.stringMatching(/^set-/),
      name: "Building heights (copy)",
      shared: { context: { collapsed: true }, outcomes: { collapsed: true } },
    });
    expect(d.scenarios).toEqual([{
      id: expect.any(String),
      name: "Twice as tall",
      color: "#e86a3c",
      description: "Heights doubled",
      nodes: [copyOf(d, "scale").id, copyOf(d, "map").id],
      set: d.set.id,
      context: [d.loaders[0].id],
      outcomes: [],
      collapsed: true,
      box: AT,
      source: { project: "p-src", scenario: "s1" },
    }]);
  });

  test("the set's name is one no set here has; a scenario keeps its name, and a color here is not taken twice", () => {
    const here: Scenario[] = [{ id: "x", name: "Twice as tall", color: "#E86A3C", nodes: [] }];
    const sets: ScenarioSet[] = [{ id: "a", name: "Building heights (copy)" }];
    const d = drop(plan(), { nodes: [], edges: [] }, here, sets);
    expect(d.set.name).toBe("Building heights (copy 2)");
    expect(d.scenarios[0].name).toBe("Twice as tall");
    expect(d.scenarios[0].color.toLowerCase()).not.toBe("#e86a3c");
  });

  test("two scenarios share one loader, and the shared outcomes that came are wired to both copies", () => {
    const d = drop(twoScenarios());
    expect(d.loaders).toHaveLength(1);
    const loader = d.loaders[0].id;
    const [scale, real, compare, chart] = ["scale", "real", "compare", "chart"].map((id) => copyOf(d, id));
    expect(d.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: loader, target: scale.id }),
      expect.objectContaining({ source: loader, target: real.id }),
      expect.objectContaining({ source: scale.id, target: compare.id, targetHandle: "in_0" }),
      expect.objectContaining({ source: real.id, target: compare.id, targetHandle: "in_1" }),
      expect.objectContaining({ source: compare.id, target: chart.id }),
    ]));
    // Their places relative to one another are kept, the top left at the drop.
    expect([scale.x, scale.y, real.y, compare.x, chart.x]).toEqual([50, 70, 470, 650, 1250]);
    const [tall, realHeights] = d.scenarios;
    expect(tall.set).toBe(d.set.id);
    expect(realHeights.set).toBe(d.set.id);
    expect(tall.context).toEqual([loader]);
    expect(realHeights.outcomes).toEqual([compare.id, chart.id]);
    expect([tall.box, realHeights.box]).toEqual([{ x: 50, y: 70 }, { x: 50, y: 470 }]);
    expect(d.scenarios.every((s) => s.collapsed)).toBe(true);
    // The compare step's own saved output comes to its copy.
    expect(d.outputs).toContainEqual({ source: "compare", node: compare.id });
  });

  test("a drop never reuses what an earlier one brought: each set brings its own context", () => {
    const first = drop(plan());
    // The first drop's loader, as the canvas holds it.
    const loaders: SpecNode[] = first.loaders.map((loader) => ({
      id: "brought-before", type: "curio.builtin/data-loading", metadata: { copiedFrom: loader.copiedFrom },
    }));
    const second = drop(plan(), { nodes: [...loaders, ...first.nodes], edges: first.edges }, first.scenarios, [first.set]);
    expect(second.loaders).toHaveLength(1);
    expect(second.edges.some((e) => e.source === "brought-before")).toBe(false);
    expect(second.set.name).toBe("Building heights (copy 2)");
  });

  test("a value node of the context arrives as a Data Loading node over its saved value, wired where it was", () => {
    const d = drop(withSeason());
    expect(d.loaders.map((loader) => loader.source)).toEqual(["load", "season"]);
    const season = d.loaders[1];
    expect(season.copiedFrom).toEqual(["season"]);
    expect(season.position.x).toBeLessThan(AT.x);
    const scale = copyOf(d, "scale");
    expect(d.edges).toContainEqual(
      expect.objectContaining({ source: season.id, sourceHandle: "out", target: scale.id, targetHandle: "in_1" }),
    );
    expect(d.outputs).toContainEqual({ source: "season", node: season.id });
    // Only the levers are copied.
    expect(d.nodes.some((n) => (n.metadata?.copiedFrom as string[] | undefined)?.at(-1) === "season")).toBe(false);
  });

  test("a scenario with no levers left is refused", () => {
    const none = plan({ scenarios: [{ ...TALL, levers: [], context: [], outcomes: [] }], dataflow: { nodes: [], edges: [] } });
    expect(planScenarioDrop(none, { nodes: [], edges: [] }, [], [], { newId: counter(), at: AT })).toEqual({
      error: '"Twice as tall" has no nodes to bring.',
    });
  });
});

describe("loaderNodes and dropGraph", () => {
  test("a loader is the Data Loading node a Data Catalog drop makes, reading the copy", () => {
    const d = drop(plan());
    const loaderId = d.loaders[0].id;
    const dataset = { id: "computed.p-here.abc", title: "Data Loading", format: "csv", origin: "computed" };

    const [node] = loaderNodes(d.loaders, { [loaderId]: dataset }, buildDatasetLoaderNodeOptions);

    const fromCatalog = buildDatasetLoaderNodeOptions(dataset as any, d.loaders[0].position);
    expect(node).toMatchObject({
      id: loaderId,
      type: "curio.builtin/data-loading",
      x: d.loaders[0].position.x,
      y: d.loaders[0].position.y,
      content: fromCatalog.code,
    });
    expect(node.content).toContain('curio_load_data("computed.p-here.abc")');
    expect(node.metadata).toMatchObject({
      copiedFrom: ["load"],
      datasetRefs: fromCatalog.datasetRefs,
      datasetSource: fromCatalog.datasetSource,
    });
  });

  test("a loader whose dataset did not arrive is left out, and so are its edges", () => {
    const d = drop(plan());
    const graph = dropGraph(d, loaderNodes(d.loaders, {}, buildDatasetLoaderNodeOptions));
    expect(graph.nodes.map((n) => n.id).sort()).toEqual(d.nodes.map((n) => n.id).sort());
    expect(graph.edges.some((e) => e.source === d.loaders[0].id)).toBe(false);
    expect(graph.edges).toHaveLength(1);
  });
});
