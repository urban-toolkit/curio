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
