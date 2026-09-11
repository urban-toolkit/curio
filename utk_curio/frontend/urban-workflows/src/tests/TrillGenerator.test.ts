import { TrillGenerator } from "../TrillGenerator";

describe("TrillGenerator", () => {
  beforeEach(() => {
    TrillGenerator.reset();
  });

  test("preserves custom node dimensions in exported specs", () => {
    const spec = TrillGenerator.generateTrill(
      [
        {
          type: "DATA_LOADING",
          position: { x: 10, y: 20 },
          data: {
            nodeId: "node-1",
            nodeWidth: 640,
            nodeHeight: 360,
          },
        },
      ],
      [],
      "Imported Workflow"
    );

    expect(spec.dataflow.nodes).toHaveLength(1);
    expect(spec.dataflow.nodes[0]).toMatchObject({
      id: "node-1",
      width: 640,
      height: 360,
    });
  });

  test("persists edge handles so UUID-id edges keep their merge slot (dev/64)", () => {
    const spec = TrillGenerator.generateTrill(
      [],
      [
        {
          // Agent-built edge: UUID id carries no slot info — the persisted
          // handles are the only place `in_1` survives a save/load cycle.
          id: "b1433343-ee39-4d94-b927-d55e5bb6579d",
          source: "loader-node",
          sourceHandle: "out",
          target: "merge-node",
          targetHandle: "in_1",
        },
        {
          // Handle-less edge (interaction/legacy): fields stay omitted.
          id: "plain-edge",
          source: "a",
          target: "b",
          sourceHandle: null,
          targetHandle: undefined,
        },
      ],
      "Imported Workflow"
    );

    expect(spec.dataflow.edges).toHaveLength(2);
    expect(spec.dataflow.edges[0]).toMatchObject({
      id: "b1433343-ee39-4d94-b927-d55e5bb6579d",
      sourceHandle: "out",
      targetHandle: "in_1",
    });
    expect(spec.dataflow.edges[1]).not.toHaveProperty("sourceHandle");
    expect(spec.dataflow.edges[1]).not.toHaveProperty("targetHandle");
  });
});

describe("TrillGenerator provenance persistence", () => {
  beforeEach(() => {
    TrillGenerator.reset();
  });

  test("getSerializableDataflowProvenance returns empty structure when no provenance", () => {
    const data = TrillGenerator.getSerializableDataflowProvenance();
    expect(data.latest).toBe("");
    expect(data.graph.nodes).toHaveLength(0);
    expect(data.versions).toEqual({});
  });

  test("loadDataflowProvenance restores provenanceJSON, latestTrill, list_of_trills", () => {
    const saved = {
      id: "wf",
      latest: "wf_123",
      graph: {
        id: "wf",
        nodes: [{ id: "wf_123", label: "wf (123)", timestamp: 123 }],
        edges: [],
      },
      versions: {
        wf_123: {
          dataflow: {
            nodes: [],
            edges: [],
            name: "wf",
            task: "",
            timestamp: 123,
            provenance_id: "wf",
            packages: [],
          },
        },
      },
    };
    TrillGenerator.loadDataflowProvenance(saved);
    expect(TrillGenerator.latestTrill).toBe("wf_123");
    expect(TrillGenerator.provenanceJSON.nodes).toHaveLength(1);
    expect(TrillGenerator.list_of_trills["wf_123"]).toBeDefined();
  });

  test("round-trip: serialize then restore produces identical state", () => {
    TrillGenerator.addNewVersionProvenance([], [], "wf", "", "Initial");
    const saved = TrillGenerator.getSerializableDataflowProvenance();
    const latestBefore = TrillGenerator.latestTrill;
    const nodesBefore = TrillGenerator.provenanceJSON.nodes.length;

    TrillGenerator.reset();
    TrillGenerator.loadDataflowProvenance(saved);

    expect(TrillGenerator.latestTrill).toBe(latestBefore);
    expect(TrillGenerator.provenanceJSON.nodes).toHaveLength(nodesBefore);
  });

  test("loadDataflowProvenance with null/undefined does nothing", () => {
    TrillGenerator.loadDataflowProvenance(null);
    expect(TrillGenerator.latestTrill).toBe("");
    TrillGenerator.loadDataflowProvenance(undefined);
    expect(TrillGenerator.provenanceJSON.nodes).toHaveLength(0);
  });
});

describe("TrillGenerator node appearance (dev/89)", () => {
  beforeEach(() => {
    TrillGenerator.reset();
  });

  test("persists per-node appearance + title at the canonical shape (dev/89)", () => {
    const spec = TrillGenerator.generateTrill(
      [
        {
          type: "CURIO_UNIVERSAL_NODE",
          position: { x: 0, y: 0 },
          data: {
            nodeId: "note-1",
            nodeType: "ai.agent.notes/note-kind",
            appearance: { backgroundColor: "#fbd3e0" },
            title: "Research note",
          },
        },
        {
          // No appearance/title: the serialized node stays byte-identical
          // to the pre-dev/89 shape (no metadata key at all).
          type: "CURIO_UNIVERSAL_NODE",
          position: { x: 5, y: 5 },
          data: { nodeId: "plain-1", nodeType: "curio.builtin/computation-analysis" },
        },
      ],
      [],
      "Imported Workflow"
    );

    const byId = Object.fromEntries(spec.dataflow.nodes.map((n: any) => [n.id, n]));
    expect(byId["note-1"].metadata.appearance).toEqual({ backgroundColor: "#fbd3e0" });
    expect(byId["note-1"].title).toBe("Research note");
    expect(byId["plain-1"].metadata).toBeUndefined();
    expect(byId["plain-1"].title).toBeUndefined();
  });
});

describe("TrillGenerator node comments (#237)", () => {
  beforeEach(() => {
    TrillGenerator.reset();
  });

  test("persists per-node comments at metadata.comments", () => {
    // The reported bug: a newly dragged module saved fine, comments did not.
    // They were held in NodeContainer's local useState and read by nothing, so
    // the serializer never saw them. Both halves are covered here - the node
    // carrying comments emits them, and the one without stays byte-identical
    // to the pre-fix shape (no `metadata` key at all).
    const comments = [
      {
        id: "c-1",
        text: "check the CRS before the join",
        author: "ada",
        authorName: "Ada Lovelace",
        createdAt: "2026-08-30T12:00:00.000Z",
        resolved: false,
      },
    ];
    const spec = TrillGenerator.generateTrill(
      [
        {
          type: "CURIO_UNIVERSAL_NODE",
          position: { x: 0, y: 0 },
          data: {
            nodeId: "discussed-1",
            nodeType: "curio.builtin/computation-analysis",
            comments,
          },
        },
        {
          type: "CURIO_UNIVERSAL_NODE",
          position: { x: 5, y: 5 },
          data: { nodeId: "plain-1", nodeType: "curio.builtin/computation-analysis" },
        },
      ],
      [],
      "Imported Workflow"
    );

    const byId = Object.fromEntries(spec.dataflow.nodes.map((n: any) => [n.id, n]));
    expect(byId["discussed-1"].metadata.comments).toEqual(comments);
    expect(byId["plain-1"].metadata).toBeUndefined();
  });

  test("emits nothing for an empty comment list", () => {
    // Deleting the last comment must not leave `metadata: { comments: [] }`
    // behind - that would dirty every example in the committed corpus the
    // first time someone opened and saved one.
    const spec = TrillGenerator.generateTrill(
      [
        {
          type: "CURIO_UNIVERSAL_NODE",
          position: { x: 0, y: 0 },
          data: {
            nodeId: "emptied-1",
            nodeType: "curio.builtin/computation-analysis",
            comments: [],
          },
        },
      ],
      [],
      "Imported Workflow"
    );

    expect(spec.dataflow.nodes[0].metadata).toBeUndefined();
  });
});

describe("the dataflow goal", () => {
  beforeEach(() => {
    TrillGenerator.reset();
  });

  test("round-trips through the spec's task field", () => {
    // Five built-in agents declare `workflowGoal` in their manifest reads, and
    // the Dataflow Task Planner exists to turn a goal into a plan. `task` has
    // always been a spec field, but both save paths hardcoded "" and the load
    // path ignored the argument it was handed, so a goal never survived a
    // reload and the agents always saw an empty string.
    const spec = TrillGenerator.generateTrill(
      [],
      [],
      "Heat risk",
      "Find neighborhoods with low canopy and high heat",
    );
    expect(spec.dataflow.task).toBe(
      "Find neighborhoods with low canopy and high heat",
    );
  });

  test("an absent goal is an empty string, not undefined", () => {
    const spec = TrillGenerator.generateTrill([], [], "Untitled");
    expect(spec.dataflow.task).toBe("");
  });
});

/**
 * Version ids must be unique.
 *
 * A version was keyed `<name>_<timestamp>` at millisecond resolution, so two
 * versions cut inside one millisecond collapsed onto a single `versions` key,
 * the graph grew duplicate node ids, and the edge between them became a
 * self-loop with a duplicate id. React then reported "two children with the
 * same key" in the provenance window — meaning a version could be silently
 * dropped or duplicated. Saved projects on disk already contain this shape.
 */
describe("TrillGenerator provenance ids are unique", () => {
  beforeEach(() => {
    TrillGenerator.reset();
    jest.restoreAllMocks();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("gives two versions cut in the same millisecond distinct ids", () => {
    jest.spyOn(Date, "now").mockReturnValue(1700000000000);

    TrillGenerator.addNewVersionProvenance([], [], "wf", "", "Initial");
    TrillGenerator.addNewVersionProvenance([], [], "wf", "", "Node added");

    const ids = TrillGenerator.provenanceJSON.nodes.map((n: any) => n.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(Object.keys(TrillGenerator.list_of_trills)).toHaveLength(2);
  });

  it("never emits a self-loop edge, and keeps edge ids unique", () => {
    jest.spyOn(Date, "now").mockReturnValue(1700000000000);

    TrillGenerator.addNewVersionProvenance([], [], "wf", "", "Initial");
    TrillGenerator.addNewVersionProvenance([], [], "wf", "", "Node added");
    TrillGenerator.addNewVersionProvenance([], [], "wf", "", "Node deleted");

    const edges = TrillGenerator.provenanceJSON.edges;
    for (const edge of edges) {
      expect(edge.source).not.toBe(edge.target);
    }
    const edgeIds = edges.map((e: any) => e.id);
    expect(new Set(edgeIds).size).toBe(edgeIds.length);
  });

  it("keeps every version reachable by the id the graph reports", () => {
    // TrillProvenanceWindow feeds the React Flow node id straight back into
    // switchProvenanceTrill, so every graph id must be a versions key.
    jest.spyOn(Date, "now").mockReturnValue(1700000000000);

    TrillGenerator.addNewVersionProvenance([], [], "wf", "", "Initial");
    TrillGenerator.addNewVersionProvenance([], [], "wf", "", "Node added");

    for (const node of TrillGenerator.provenanceJSON.nodes) {
      expect(TrillGenerator.list_of_trills[node.id]).toBeDefined();
    }
  });

  it("still loads an old file whose ids carry no suffix", () => {
    TrillGenerator.loadDataflowProvenance({
      id: "wf",
      latest: "wf_123",
      graph: {
        id: "wf",
        nodes: [{ id: "wf_123", label: "wf (123)", timestamp: 123, preview: null }],
        edges: [],
      },
      versions: { wf_123: { dataflow: { nodes: [], edges: [] } } },
    });

    expect(TrillGenerator.latestTrill).toBe("wf_123");
    expect(TrillGenerator.list_of_trills["wf_123"]).toBeDefined();

    // And a version cut after the load does not reuse the loaded key.
    jest.spyOn(Date, "now").mockReturnValue(123);
    TrillGenerator.addNewVersionProvenance([], [], "wf", "", "Node added");
    expect(Object.keys(TrillGenerator.list_of_trills)).toHaveLength(2);
  });
});

describe("TrillGenerator Spatial Join settings (#262)", () => {
  beforeEach(() => {
    TrillGenerator.reset();
  });

  test("persists the chosen polygon property at metadata.spatialJoin, and only when set", () => {
    const spec = TrillGenerator.generateTrill(
      [
        {
          type: "CURIO_UNIVERSAL_NODE",
          position: { x: 0, y: 0 },
          data: {
            nodeId: "sj-1",
            nodeType: "curio.builtin/spatial-join",
            spatialJoin: { nameProperty: "pri_neigh" },
          },
        },
        {
          type: "CURIO_UNIVERSAL_NODE",
          position: { x: 5, y: 5 },
          data: { nodeId: "sj-2", nodeType: "curio.builtin/spatial-join" },
        },
      ],
      [],
      "Imported Workflow"
    );

    const byId = Object.fromEntries(spec.dataflow.nodes.map((n: any) => [n.id, n]));
    expect(byId["sj-1"].metadata.spatialJoin).toEqual({ nameProperty: "pri_neigh" });
    expect(byId["sj-2"].metadata).toBeUndefined();
  });
});
