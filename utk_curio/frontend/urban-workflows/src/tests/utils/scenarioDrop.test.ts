/**
 * One scenario dragged in from the Scenario Catalog (#662), as the canvas
 * builds it: fresh ids naming their originals, one Data Loading node per node
 * whose output crosses into what is copied, wired where it was, saved outputs
 * sent to the copies that make them, everything collapsed. The first drop of
 * a set's scenario makes the set's copy, named as the set and recording where
 * it came from; a later drop of another scenario of that set joins the copy,
 * found by where it came from, reuses its context, and wires a shared outcome
 * that lands now to the earlier copies; a scenario the copy holds is refused.
 */
import { buildDatasetLoaderNodeOptions } from "../../services/datasetCatalog/datasetApplication";
import type { ScenarioCopyPlan } from "../../services/scenarioCatalog/scenarioCatalogTypes";
import type { SpecNode } from "../../utils/scenarios/duplicateSelection";
import type { Scenario, ScenarioSet } from "../../utils/scenarios/scenarioModel";
import {
  alreadyInCopy,
  dropGraph,
  loaderNodes,
  planScenarioDrop,
  presentInCopy,
  type ScenarioDrop,
} from "../../utils/scenarios/scenarioDrop";

const AT = { x: 50, y: 70 };

function counter(prefix = "new") {
  let n = 0;
  return () => `${prefix}-${++n}`;
}

const TALL = { id: "s1", name: "Twice as tall", color: "#e86a3c", description: "Heights doubled" };
const REAL = { id: "s2", name: "Real heights", color: "#2a9d8f", description: "" };
const POOL = { nodeId: "pool", label: "Data pool", source: { nodeId: "load", copiedFrom: [], datasetId: "computed.p-src.load" } };

function plan(overrides: Partial<ScenarioCopyPlan> = {}): ScenarioCopyPlan {
  return {
    scenario: TALL,
    set: { id: "heights", name: "Building heights" },
    project: { id: "p-src", name: "Shadows" },
    nodes: ["scale", "map"],
    last: [],
    context: [POOL],
    shared: [],
    outcomes: [],
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
 *  that returns its widget's value) wired into the scale node's second circle. */
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

const computation = (id: string, x: number, y: number) => ({
  id, type: "curio.builtin/computation-analysis@1", x, y, content: "return input_0",
});

/** A set of two scenarios, each scaling the pooled heights its own way; a
 *  compare step reads both and feeds a chart, the set's shared outcomes. The
 *  first drop brings "Twice as tall" alone: the outcomes wait for the other. */
function firstOfTheSet(): ScenarioCopyPlan {
  return plan({
    nodes: ["scale"],
    outcomes: ["compare", "chart"],
    dataflow: {
      nodes: [computation("scale", 600, 100)],
      edges: [{ id: "e1", source: "pool", target: "scale", sourceHandle: "out", targetHandle: "in" }],
    },
  });
}

/** Then "Real heights", with "Twice as tall" in the copy: the outcomes land. */
function secondOfTheSet(): ScenarioCopyPlan {
  return plan({
    scenario: REAL,
    nodes: ["real"],
    shared: [
      { nodeId: "compare", label: "Compare", scenarios: ["s2", "s1"], sources: ["compare"] },
      { nodeId: "chart", label: "Vis Vega", scenarios: ["s2", "s1"], sources: ["compare"] },
    ],
    outcomes: ["compare", "chart"],
    dataflow: {
      nodes: [computation("real", 600, 500), computation("compare", 1200, 300), computation("chart", 1800, 300)],
      edges: [
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
  newId = counter(),
): ScenarioDrop {
  const built = planScenarioDrop(p, live, scenarios, sets, { newId, at: AT });
  if ("error" in built) throw new Error(built.error);
  return built;
}

const copyOf = (d: ScenarioDrop, original: string) =>
  d.nodes.find((n) => (n.metadata?.copiedFrom as string[] | undefined)?.at(-1) === original)!;

/** The canvas after *d*, in the saved shape a later drop reads: its loaders
 *  as the Data Loading nodes they become, and its copies. */
function canvasAfter(d: ScenarioDrop): { nodes: SpecNode[]; edges: any[] } {
  const loaders: SpecNode[] = d.loaders.map((loader) => ({
    id: loader.id, type: "curio.builtin/data-loading", metadata: { copiedFrom: loader.copiedFrom },
  }));
  return { nodes: [...loaders, ...d.nodes], edges: d.edges };
}

describe("planScenarioDrop", () => {
  test("its own nodes are copied with fresh ids, each naming its original, placed at the drop", () => {
    const d = drop(plan());
    const scale = copyOf(d, "scale");
    const map = copyOf(d, "map");
    expect(new Set([scale.id, map.id]).size).toBe(2);
    expect([scale.id, map.id]).not.toContain("scale");
    expect(scale.metadata?.copiedFrom).toEqual(["first", "scale"]);
    expect(map.metadata?.copiedFrom).toEqual(["map"]);
    // Their top-left corner lands where the scenario was dropped.
    expect([scale.x, scale.y, map.x, map.y]).toEqual([50, 70, 650, 70]);
    expect(d.edges).toContainEqual(expect.objectContaining({ source: scale.id, target: map.id, targetHandle: "in" }));
  });

  test("each node whose output crosses into it arrives as one Data Loading node, wired where it was", () => {
    const d = drop(plan());
    expect(d.loaders).toHaveLength(1);
    const [loader] = d.loaders;
    expect(loader.source).toBe("load");
    expect(loader.copiedFrom).toEqual(["load"]);
    expect(loader.position.x).toBeLessThan(AT.x);
    expect(loader.goal).toBe('Shared context of "Building heights": a copy of what Data pool passed on in Shadows.');
    const scale = copyOf(d, "scale");
    expect(d.edges).toContainEqual(expect.objectContaining({ source: loader.id, sourceHandle: "out", target: scale.id }));
    expect(d.edges.some((e) => e.source === "pool" || e.target === "pool")).toBe(false);
  });

  test("the server is told which saved output each copy gets: the context's, what stands for its last nodes, and for a shared outcome landing", () => {
    const alone = drop(plan());
    expect(alone.outputs).toEqual([{ source: "load", node: alone.loaders[0].id }]);
    // Its last node, the map, draws what the scale node makes: the scale
    // node's saved output comes to its copy.
    const shown = drop(plan({ last: [{ nodeId: "map", sources: ["scale"] }] }));
    expect(shown.outputs).toEqual([
      { source: "load", node: shown.loaders[0].id },
      { source: "scale", node: copyOf(shown, "scale").id },
    ]);
    const first = drop(firstOfTheSet());
    const second = drop(secondOfTheSet(), canvasAfter(first), first.scenarios, first.sets, counter("next"));
    // The context came with the first drop; the compare step's own saved
    // output comes to its copy, and the chart, which saves nothing, stands
    // for it.
    expect(second.outputs).toEqual([{ source: "compare", node: copyOf(second, "compare").id }]);
  });

  test("the first drop of a set makes its copy, named as the set, recording where it came from, all collapsed", () => {
    const d = drop(plan());
    expect(d.made).toBe(true);
    expect(d.set).toEqual({
      id: `set-${d.scenario.id}`,
      name: "Building heights",
      shared: { context: { collapsed: true }, outcomes: { collapsed: true } },
      source: { project: "p-src", set: "heights" },
    });
    expect(d.sets).toEqual([d.set]);
    expect(d.scenarios).toEqual([d.scenario]);
    expect(d.scenario).toEqual({
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
    });
  });

  test("the copy's name is one no set here has; a scenario keeps its name, and a color here is not taken twice", () => {
    const here: Scenario[] = [{ id: "x", name: "Twice as tall", color: "#E86A3C", nodes: [], set: "a" }];
    const sets: ScenarioSet[] = [{ id: "a", name: "Building heights" }];
    const d = drop(plan(), { nodes: [], edges: [] }, here, sets);
    expect(d.set.name).toBe("Building heights 2");
    expect(d.scenario.name).toBe("Twice as tall");
    expect(d.scenario.color.toLowerCase()).not.toBe("#e86a3c");
    expect(d.sets).toEqual([...sets, d.set]);
  });

  test("a later drop of another scenario of the set joins the copy, reuses its context, and wires the shared outcomes that land to the earlier copies", () => {
    const first = drop(firstOfTheSet());
    const before = canvasAfter(first);
    const brought = before.nodes[0].id;
    const scaleCopy = copyOf(first, "scale").id;
    expect(first.scenario.outcomes).toEqual([]);

    const second = drop(secondOfTheSet(), before, first.scenarios, first.sets, counter("next"));

    expect(second.made).toBe(false);
    expect(second.set).toBe(first.set);
    expect(second.sets).toEqual(first.sets);
    // The context the first drop brought is read again: no loader is made.
    expect(second.loaders).toEqual([]);
    const [real, compare, chart] = ["real", "compare", "chart"].map((id) => copyOf(second, id));
    expect(second.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: brought, target: real.id }),
      expect.objectContaining({ source: scaleCopy, target: compare.id, targetHandle: "in_0" }),
      expect.objectContaining({ source: real.id, target: compare.id, targetHandle: "in_1" }),
      expect.objectContaining({ source: compare.id, target: chart.id }),
    ]));
    expect(second.reused.map((n) => n.id).sort()).toEqual([brought, scaleCopy].sort());
    expect(second.scenario.set).toBe(first.set.id);
    expect(second.scenario.context).toEqual([brought]);
    expect(second.scenario.outcomes).toEqual([compare.id, chart.id]);
    // The earlier scenario lists the shared outcomes that landed too.
    const earlier = second.scenarios.find((s) => s.id === first.scenario.id)!;
    expect(earlier.outcomes).toEqual([compare.id, chart.id]);
    expect(second.scenarios.map((s) => s.id)).toEqual([first.scenario.id, second.scenario.id]);
  });

  test("the join is on where the copy came from, never on its name", () => {
    const first = drop(firstOfTheSet());
    // A set of the same name made here, and a copy of a set of the same id
    // from another project, hold "Twice as tall": neither is the copy.
    const ownSet: ScenarioSet = { ...first.set, source: undefined };
    const otherProject: ScenarioSet = { ...first.set, id: "set-other", source: { project: "p-else", set: "heights" } };
    for (const set of [ownSet, otherProject]) {
      const scenarios = first.scenarios.map((s) => ({ ...s, set: set.id }));
      const d = drop(secondOfTheSet(), canvasAfter(first), scenarios, [set], counter("next"));
      expect([d.made, d.set.name]).toEqual([true, "Building heights 2"]);
      expect(d.loaders).toHaveLength(1);
      expect(d.reused).toEqual([]);
    }
  });

  test("a scenario the copy holds already is refused, saying so", () => {
    const first = drop(plan());
    const from = { projectId: "p-src", setId: "heights", scenarioId: "s1", name: "Twice as tall" };
    expect(presentInCopy(from, first.scenarios, first.sets)).toEqual(["s1"]);
    const refusal = '"Twice as tall" is already in the scenario set "Building heights" here. A scenario comes in once.';
    expect(alreadyInCopy(from, first.scenarios, first.sets)).toBe(refusal);
    expect(planScenarioDrop(plan(), canvasAfter(first), first.scenarios, first.sets, { newId: counter("next"), at: AT }))
      .toEqual({ error: refusal });
    // Another scenario of the set is not.
    expect(alreadyInCopy({ ...from, scenarioId: "s2", name: "Real heights" }, first.scenarios, first.sets)).toBeNull();
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
    // Only its own nodes are copied.
    expect(d.nodes.some((n) => (n.metadata?.copiedFrom as string[] | undefined)?.at(-1) === "season")).toBe(false);
  });

  test("a scenario with no nodes left is refused", () => {
    const none = plan({ nodes: [], dataflow: { nodes: [], edges: [] } });
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

  test("a join's graph holds the nodes of the copy its edges come from", () => {
    const first = drop(firstOfTheSet());
    const second = drop(secondOfTheSet(), canvasAfter(first), first.scenarios, first.sets, counter("next"));
    const graph = dropGraph(second, []);
    const ids = new Set(graph.nodes.map((n) => n.id));
    expect(graph.edges.every((e) => ids.has(e.source) && ids.has(e.target))).toBe(true);
  });
});
