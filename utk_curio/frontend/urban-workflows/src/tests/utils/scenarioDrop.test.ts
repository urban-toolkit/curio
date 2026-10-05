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
        { id: "scale", type: "curio.builtin/computation-analysis@1", x: 600, y: 100, content: "return arg", metadata: { copiedFrom: ["first"] } },
        { id: "map", type: "curio.builtin/autk-grammar@1", x: 1200, y: 100, content: "{}" },
      ],
      edges: [
        { id: "e1", source: "pool", target: "scale", sourceHandle: "out", targetHandle: "in" },
        { id: "e2", source: "scale", target: "map", sourceHandle: "out", targetHandle: "in" },
      ],
    },
    packages: [],
    problems: [],
    ...overrides,
  };
}

const SEASON: SpecNode = {
  id: "season",
  type: "curio.builtin/parameter@1",
  x: 0,
  y: 400,
  content: "",
  metadata: { widgets: [{ name: "season", type: "text", default: "winter", value: "summer" }] },
};

function withSeason(): ScenarioCopyPlan {
  const base = plan();
  return {
    ...base,
    context: [...base.context, { nodeId: "season", label: "Parameter", parameter: true }],
    dataflow: { ...base.dataflow, nodes: [...base.dataflow.nodes, SEASON] },
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

  test("a Parameter node of the context arrives as a copy with its value, beside the box", () => {
    const d = drop(withSeason());
    const season = copyOf(d, "season");
    expect(season.id).not.toBe("season");
    expect((season.metadata?.widgets as any[])[0]).toMatchObject({ name: "season", value: "summer" });
    expect(season.x).toBeLessThan(AT.x);
    expect(d.scenario.nodes).not.toContain(season.id);
    // It is reached by its name, not an edge, and is not a saved output.
    expect(d.edges.some((e) => e.source === season.id)).toBe(false);
    expect(d.outputs.some((o) => o.node === season.id)).toBe(false);
  });

  test("a parameter name this dataflow already uses is refused, naming it", () => {
    const mine: SpecNode = { ...SEASON, id: "my-season", metadata: { widgets: [{ name: "season", type: "text", default: "dry" }] } };
    const built = planScenarioDrop(withSeason(), { nodes: [mine], edges: [] }, [], { newId: counter(), at: AT });
    expect(built).toEqual({
      error: 'This dataflow already has a parameter named "season". Rename it, then drag "Twice as tall" again.',
    });
  });

  test("a second scenario of the same project reuses the context the first brought", () => {
    const first = drop(withSeason());
    const loader: SpecNode = { id: first.loaders[0].id, type: "curio.builtin/data-loading", metadata: { copiedFrom: first.loaders[0].copiedFrom } };
    const live = { nodes: [loader, copyOf(first, "season"), ...first.nodes.filter((n) => n.id !== copyOf(first, "season").id)], edges: first.edges };

    const second = drop(withSeason(), live, [first.scenario]);

    expect(second.loaders).toEqual([]);
    expect(second.reused.map((n) => n.id).sort()).toEqual([loader.id, copyOf(first, "season").id].sort());
    expect(second.edges).toContainEqual(expect.objectContaining({ source: loader.id, target: copyOf(second, "scale").id }));
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
