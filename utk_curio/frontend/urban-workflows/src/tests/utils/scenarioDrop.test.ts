/**
 * A scenario dragged in from the Scenario Catalog (#662), as the canvas
 * builds it: fresh ids naming their originals, one Data Loading node per
 * context input wired where the context was, outcomes' saved outputs sent to
 * the copies that make them, the scenario collapsed where it was dropped, and
 * a second drop from the same project sharing what the first brought.
 */
import { buildDatasetLoaderNodeOptions } from "../../services/datasetCatalog/datasetApplication";
import type { ScenarioCopyPlan } from "../../services/scenarioCatalog/scenarioCatalogTypes";
import type { SpecNode } from "../../utils/scenarios/duplicateSelection";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import { dropGraph, loaderNodes, planScenarioDrop, type ScenarioDrop } from "../../utils/scenarios/scenarioDrop";

const AT = { x: 50, y: 70 };

function counter() {
  let n = 0;
  return () => `new-${++n}`;
}

function plan(overrides: Partial<ScenarioCopyPlan> = {}): ScenarioCopyPlan {
  return {
    scenario: { id: "s1", name: "Twice as tall", color: "#e86a3c", description: "Heights doubled" },
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

function drop(p: ScenarioCopyPlan, live: { nodes: SpecNode[]; edges: any[] } = { nodes: [], edges: [] }, scenarios: Scenario[] = []): ScenarioDrop {
  const built = planScenarioDrop(p, live, scenarios, { newId: counter(), at: AT });
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

  test("the scenario is added collapsed where it was dropped, naming where it came from", () => {
    const d = drop(plan());
    expect(d.scenario).toEqual({
      id: expect.any(String),
      name: "Twice as tall",
      color: "#e86a3c",
      description: "Heights doubled",
      nodes: [copyOf(d, "scale").id, copyOf(d, "map").id],
      collapsed: true,
      box: AT,
      source: { project: "p-src", scenario: "s1" },
    });
  });

  test("a name and a color this dataflow already uses are not taken twice", () => {
    const here: Scenario[] = [{ id: "x", name: "Twice as tall", color: "#E86A3C", nodes: [] }];
    const d = drop(plan(), { nodes: [], edges: [] }, here);
    expect(d.scenario.name).toBe("Twice as tall (2)");
    expect(d.scenario.color.toLowerCase()).not.toBe("#e86a3c");
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

  test("a second scenario of the same project reuses the context the first brought", () => {
    const first = drop(withSeason());
    const loaders: SpecNode[] = first.loaders.map((loader) => ({
      id: loader.id, type: "curio.builtin/data-loading", metadata: { copiedFrom: loader.copiedFrom },
    }));
    const live = { nodes: [...loaders, ...first.nodes], edges: first.edges };

    const second = drop(withSeason(), live, [first.scenario]);

    expect(second.loaders).toEqual([]);
    expect(second.reused.map((n) => n.id).sort()).toEqual(loaders.map((n) => n.id).sort());
    expect(second.edges).toContainEqual(expect.objectContaining({ source: loaders[0].id, target: copyOf(second, "scale").id }));
    expect(second.edges).toContainEqual(
      expect.objectContaining({ source: loaders[1].id, target: copyOf(second, "scale").id, targetHandle: "in_1" }),
    );
    expect(second.outputs).toEqual([{ source: "scale", node: copyOf(second, "scale").id }]);
    expect(second.nodes.some((n) => (n.metadata?.copiedFrom as string[] | undefined)?.at(-1) === "season")).toBe(false);
  });

  test("a node another project's drop brought is never taken for this one's context", () => {
    const first = drop(plan());
    const loader: SpecNode = { id: first.loaders[0].id, type: "curio.builtin/data-loading", metadata: { copiedFrom: ["load"] } };
    const elsewhere = { ...first.scenario, source: { project: "p-other", scenario: "s1" } };

    const second = drop(plan(), { nodes: [loader], edges: [] }, [elsewhere]);

    expect(second.reused).toEqual([]);
    expect(second.loaders).toHaveLength(1);
  });

  test("a scenario with no levers left is refused", () => {
    expect(planScenarioDrop(plan({ levers: [] }), { nodes: [], edges: [] }, [], { newId: counter(), at: AT })).toEqual({
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
