import {
  downstreamFromDataflowUsage,
  formatNodeTypeLabel,
  lineageNodesFromDataflowUsage,
  lineageUsageSummary,
  producerNodeIdForDataset,
  selectDatasetDownstreamUsage,
  selectDatasetLineage,
  selectDatasetUpstreamLineage,
  upstreamOriginCaption,
  type LineageCanvasNode,
} from "../../services/datasetLineage/datasetLineageResolver";
import type { DatasetCatalogItem, DatasetDataflowUsageRef } from "../../services/datasetCatalog";

const DATASET_ID = "ds-1";

function canvasNode(overrides: Partial<NonNullable<LineageCanvasNode["data"]>> = {}): LineageCanvasNode {
  return {
    data: {
      nodeId: "node-1",
      // A generic *consumer* node by default. Data Loading nodes are the
      // dataset's source (carrier), not consumers, so tests that exercise the
      // binding-consumer path use a non-loading type; loader tests set
      // ``nodeType`` to a data-loading id explicitly.
      nodeType: "COMPUTE_ANALYSIS",
      ...overrides,
    },
  };
}

function catalogItem(overrides: Partial<DatasetCatalogItem> = {}): DatasetCatalogItem {
  return {
    id: DATASET_ID,
    title: "Test Dataset",
    origin: "imported",
    format: "geojson",
    uri: "file:///tmp/test.geojson",
    consumerNodeIds: [],
    updatedAt: new Date().toISOString(),
    tags: [],
    ...overrides,
  };
}

describe("selectDatasetDownstreamUsage", () => {
  it("returns no consumers for an empty canvas", () => {
    const usage = selectDatasetDownstreamUsage({ datasetId: DATASET_ID, nodes: [] });
    expect(usage.consumingNodes).toEqual([]);
    expect(usage.consumingDataflows).toEqual([]);
  });

  it("finds a node consuming via datasetRefs", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      nodes: [canvasNode({ datasetRefs: [DATASET_ID] })],
    });
    expect(usage.consumingNodes).toHaveLength(1);
    expect(usage.consumingNodes[0]).toMatchObject({
      nodeId: "node-1",
      usageType: "parameter",
      status: "active",
    });
  });

  it("finds a node consuming via appliedDatasets and marks it as input usage", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      nodes: [
        canvasNode({
          appliedDatasets: { [DATASET_ID]: { id: DATASET_ID, title: "Test Dataset" } },
        }),
      ],
    });
    expect(usage.consumingNodes).toHaveLength(1);
    expect(usage.consumingNodes[0].usageType).toBe("input");
  });

  it("ignores nodes that reference other datasets", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      nodes: [canvasNode({ datasetRefs: ["other-dataset"] })],
    });
    expect(usage.consumingNodes).toEqual([]);
  });

  it("dedupes duplicate references on the same node", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      nodes: [
        canvasNode({
          datasetRefs: [DATASET_ID, DATASET_ID],
          appliedDatasets: { [DATASET_ID]: { id: DATASET_ID } },
        }),
      ],
    });
    expect(usage.consumingNodes).toHaveLength(1);
  });

  it("groups multiple consuming nodes into a dataflow usage with usageCount", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      dataflowId: "flow-1",
      dataflowName: "Accessibility Analysis",
      nodes: [
        canvasNode({ nodeId: "node-1", datasetRefs: [DATASET_ID] }),
        canvasNode({ nodeId: "node-2", nodeType: "COMPUTE_ANALYSIS", datasetRefs: [DATASET_ID] }),
        canvasNode({ nodeId: "node-3", datasetRefs: ["unrelated"] }),
      ],
    });
    expect(usage.consumingNodes).toHaveLength(2);
    expect(usage.consumingDataflows).toHaveLength(1);
    expect(usage.consumingDataflows[0]).toMatchObject({
      dataflowId: "flow-1",
      dataflowName: "Accessibility Analysis",
      usageCount: 2,
      nodeIds: ["node-1", "node-2"],
      status: "active",
    });
  });

  it("marks consumers stale from nodeExecStatus", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      nodes: [canvasNode({ datasetRefs: [DATASET_ID] })],
      nodeExecStatus: { "node-1": "stale" },
    });
    expect(usage.consumingNodes[0].status).toBe("stale");
    expect(usage.consumingDataflows[0].status).toBe("stale");
  });

  it("reports persisted consumer ids with no canvas node as unresolved", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      nodes: [],
      persistedConsumerNodeIds: ["ghost-node"],
    });
    expect(usage.consumingNodes).toHaveLength(1);
    expect(usage.consumingNodes[0]).toMatchObject({
      nodeId: "ghost-node",
      status: "unresolved",
      usageType: "unknown",
    });
    expect(usage.consumingDataflows[0].status).toBe("unresolved");
  });

  it("does not duplicate persisted ids that match live canvas consumers", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      nodes: [canvasNode({ datasetRefs: [DATASET_ID] })],
      persistedConsumerNodeIds: ["node-1"],
    });
    expect(usage.consumingNodes).toHaveLength(1);
    expect(usage.consumingNodes[0].status).toBe("active");
  });

  it("uses the registry label resolver when provided", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      nodes: [canvasNode({ datasetRefs: [DATASET_ID] })],
      resolveNodeLabel: () => "Spatial Filter",
    });
    expect(usage.consumingNodes[0].nodeName).toBe("Spatial Filter");
  });

  it("resolves a computed dataset's downstream consumer from a graph edge (#141)", () => {
    // Producer "node-1" generates the dataset; "node-2" is wired downstream and
    // consumes it via data.input — no datasetRefs binding exists.
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      producerNodeId: "node-1",
      nodes: [
        canvasNode({ nodeId: "node-1" }),
        canvasNode({ nodeId: "node-2", nodeType: "COMPUTE_ANALYSIS" }),
      ],
      edges: [{ source: "node-1", target: "node-2" }],
    });
    expect(usage.consumingNodes).toHaveLength(1);
    expect(usage.consumingNodes[0]).toMatchObject({
      nodeId: "node-2",
      nodeName: "Compute Analysis",
      usageType: "input",
      status: "active",
    });
  });

  it("ignores bidirectional interaction (in/out) edges as consumers", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      producerNodeId: "node-1",
      nodes: [canvasNode({ nodeId: "node-1" }), canvasNode({ nodeId: "node-2" })],
      edges: [
        { source: "node-1", target: "node-2", sourceHandle: "in/out", targetHandle: "in/out" },
      ],
    });
    expect(usage.consumingNodes).toEqual([]);
  });

  it("does not duplicate an edge consumer that also has a dataset binding", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      producerNodeId: "node-1",
      nodes: [
        canvasNode({ nodeId: "node-1" }),
        canvasNode({ nodeId: "node-2", datasetRefs: [DATASET_ID] }),
      ],
      edges: [{ source: "node-1", target: "node-2" }],
    });
    expect(usage.consumingNodes).toHaveLength(1);
    expect(usage.consumingNodes[0].nodeId).toBe("node-2");
  });

  it("marks an edge consumer stale from nodeExecStatus", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      producerNodeId: "node-1",
      nodes: [canvasNode({ nodeId: "node-1" }), canvasNode({ nodeId: "node-2" })],
      edges: [{ source: "node-1", target: "node-2" }],
      nodeExecStatus: { "node-2": "stale" },
    });
    expect(usage.consumingNodes[0].status).toBe("stale");
  });

  it("does NOT count the dataset's own Data Loading box as a consumer when it is not connected", () => {
    // Dragging a dataset onto the canvas creates a DATA_LOADING node bound to it.
    // That node is the dataset's source, not a downstream consumer — an
    // unconnected loader must register zero downstream usage.
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      producerNodeId: "producer-x", // computed dataset, producer not on this canvas
      nodes: [
        canvasNode({
          nodeId: "loader",
          nodeType: "curio.builtin/data-loading",
          datasetRefs: [DATASET_ID],
        }),
      ],
      edges: [],
    });
    expect(usage.consumingNodes).toEqual([]);
  });

  it("counts a node wired downstream of a dropped Data Loading box", () => {
    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      nodes: [
        canvasNode({
          nodeId: "loader",
          nodeType: "curio.builtin/data-loading",
          datasetRefs: [DATASET_ID],
        }),
        canvasNode({ nodeId: "viz", nodeType: "VEGA" }),
      ],
      edges: [{ source: "loader", target: "viz" }],
    });
    expect(usage.consumingNodes.map((u) => u.nodeId)).toEqual(["viz"]);
  });
});

describe("producerNodeIdForDataset", () => {
  it("prefers an explicit producerNodeId", () => {
    expect(
      producerNodeIdForDataset({ id: "computed.x", dirName: "computed.x@1", producerNodeId: "real-node" }),
    ).toBe("real-node");
  });

  it("derives the node id from a computed dirName (version stripped)", () => {
    expect(
      producerNodeIdForDataset({ id: "computed.whatif-modified-map", dirName: "computed.whatif-modified-map@1", producerNodeId: null }),
    ).toBe("whatif-modified-map");
  });

  it("derives from the id when dirName is absent", () => {
    expect(
      producerNodeIdForDataset({ id: "computed.node-7", dirName: null, producerNodeId: null }),
    ).toBe("node-7");
  });

  it("returns null for a non-computed dataset", () => {
    expect(
      producerNodeIdForDataset({ id: "it.urbanlab.example", dirName: null, producerNodeId: null }),
    ).toBeNull();
  });

  it("returns only the NODE segment for a namespaced id (#175)", () => {
    // Never the full `<dataflowSeg>.<nodeSeg>` pair — that string poisons
    // carrier matching and leaks the dataflow UUID into the UI.
    expect(
      producerNodeIdForDataset({
        id: "computed.nc8077fbd-010d-4f6f-b7e2-a99f5df87243.whatif-data",
        dirName: "computed.nc8077fbd-010d-4f6f-b7e2-a99f5df87243.whatif-data@1",
        producerNodeId: null,
      }),
    ).toBe("whatif-data");
  });

  it("resolves the REAL canvas node id by sanitizing candidates (#175)", () => {
    // Node ids are UUIDs; the id segment is the sanitized form ("n" prefix for
    // a hex-initial uuid) — not the raw node id.
    const rawNodeId = "13AB-40cd";
    expect(
      producerNodeIdForDataset(
        { id: "computed.flow-1.n13ab-40cd", dirName: null, producerNodeId: null },
        { nodes: [{ data: { nodeId: rawNodeId } }], dataflowId: "flow-1" },
      ),
    ).toBe(rawNodeId);
  });

  it("does not attribute another dataflow's dataset to this canvas (#175)", () => {
    expect(
      producerNodeIdForDataset(
        { id: "computed.flow-other.node-1", dirName: null, producerNodeId: null },
        { nodes: [{ data: { nodeId: "node-1" } }], dataflowId: "flow-mine" },
      ),
    ).toBeNull();
  });
});

describe("selectDatasetUpstreamLineage", () => {
  it("resolves the generating node from producerNodeId", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({ origin: "computed", producerNodeId: "producer-1" }),
      nodes: [canvasNode({ nodeId: "producer-1", nodeType: "COMPUTE_ANALYSIS" })],
    });
    expect(upstream.generatingNode).toMatchObject({
      nodeId: "producer-1",
      nodeName: "Compute Analysis",
    });
    expect(upstream.originLabel).toBe("Computed");
  });

  it("keeps the producer ref without a name when the node is not on canvas", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({ origin: "computed", producerNodeId: "producer-1" }),
      nodes: [],
    });
    expect(upstream.generatingNode).toMatchObject({ nodeId: "producer-1" });
    expect(upstream.generatingNode?.nodeName).toBeUndefined();
  });

  it("has no generating node for imported datasets", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({ origin: "hub" }),
      nodes: [],
    });
    expect(upstream.generatingNode).toBeNull();
    expect(upstream.originLabel).toBe("Imported");
  });

  it("falls back to backend producer info when the producer is in another dataflow", () => {
    // Dataset opened from a dataflow that only imported it: the producer node is
    // not on this canvas, but the backend resolved its type and producing flow.
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({
        origin: "computed",
        producerNodeId: "producer-x",
        producerNodeType: "COMPUTE_ANALYSIS",
        producerDataflowId: "flow-a",
        producerDataflowName: "Flow A",
      }),
      nodes: [],
    });
    expect(upstream.generatingNode).toMatchObject({
      nodeId: "producer-x",
      nodeName: "Compute Analysis",
      nodeType: "COMPUTE_ANALYSIS",
      dataflowName: "Flow A",
    });
  });

  it("resolves the producer from the computed id when the ref dropped producerNodeId (reinstall)", () => {
    // A -map dataset uninstalled then reinstalled from a previous computed node
    // persists with producerNodeId null / origin imported, but its id/dirName
    // still encodes the producing node — upstream must resolve so the card's
    // connection badge stays consistent with the detail sidebar.
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({
        id: "computed.whatif-modified-map",
        dirName: "computed.whatif-modified-map@1",
        origin: "imported",
        producerNodeId: null,
      }),
      nodes: [canvasNode({ nodeId: "whatif-modified-map", nodeType: "COMPUTE_ANALYSIS" })],
    });
    expect(upstream.generatingNode).toMatchObject({
      nodeId: "whatif-modified-map",
      nodeName: "Compute Analysis",
    });
  });

  it("derives a producer for a computed dataset even with no canvas node (badge stays visible)", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({
        id: "computed.whatif-modified-map",
        dirName: "computed.whatif-modified-map@1",
        origin: "imported",
        producerNodeId: null,
      }),
      nodes: [],
    });
    // generatingNode non-null → useDatasetConnectionCounts upCount === 1.
    expect(upstream.generatingNode?.nodeId).toBe("whatif-modified-map");
  });

  it("does not invent a producer for a non-computed imported dataset", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({ id: "it.urbanlab.example", origin: "imported", producerNodeId: null }),
      nodes: [],
    });
    expect(upstream.generatingNode).toBeNull();
  });

  it("prefers the on-canvas producer node over backend producer info", () => {
    // When the producing dataflow IS the open canvas, live resolution wins and
    // no cross-dataflow label is attached.
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({
        origin: "computed",
        producerNodeId: "producer-1",
        producerNodeType: "DATA_EXPORT",
        producerDataflowName: "Other Flow",
      }),
      nodes: [canvasNode({ nodeId: "producer-1", nodeType: "COMPUTE_ANALYSIS" })],
    });
    expect(upstream.generatingNode).toMatchObject({
      nodeId: "producer-1",
      nodeName: "Compute Analysis",
    });
    expect(upstream.generatingNode?.dataflowName).toBeNull();
  });

  // ── upstreamInputs: what fed the producing node ─────────────────────────────
  // Written by the backend installers (resolve_upstream_inputs): one entry per
  // incoming edge of the producer, plus one per dataset bound to it.

  it("names an input node from the open canvas", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({
        origin: "computed",
        producerNodeId: "producer-1",
        upstreamInputs: [{ nodeId: "feeder-1" }],
      }),
      nodes: [
        canvasNode({ nodeId: "producer-1" }),
        canvasNode({ nodeId: "feeder-1", nodeType: "DATA_TRANSFORMATION" }),
      ],
    });
    expect(upstream.inputNodes).toEqual([
      { nodeId: "feeder-1", nodeName: "Data Transformation", nodeType: "DATA_TRANSFORMATION" },
    ]);
  });

  it("falls back to the manifest node type when the input node is off canvas", () => {
    // The dataset was opened from a dataflow that only imported it, so the node
    // that fed its producer is not here. The recorded type still names it.
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({
        origin: "computed",
        upstreamInputs: [{ nodeId: "feeder-1", nodeType: "DATA_LOADING" }],
      }),
      nodes: [],
    });
    expect(upstream.inputNodes).toEqual([
      { nodeId: "feeder-1", nodeName: "Data Loading", nodeType: "DATA_LOADING" },
    ]);
  });

  it("leaves an input node unnamed when nothing records its type", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({ origin: "computed", upstreamInputs: [{ nodeId: "feeder-1" }] }),
      nodes: [],
    });
    expect(upstream.inputNodes).toEqual([
      { nodeId: "feeder-1", nodeName: undefined, nodeType: undefined },
    ]);
  });

  it("labels a computed dataset input by its producing node, not its uuid pair", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({
        origin: "computed",
        upstreamInputs: [{ datasetId: "computed.n1899da0e-5d7a.n836a3219-01ab@1" }],
      }),
      nodes: [],
    });
    expect(upstream.sourceDatasets).toEqual([
      {
        datasetId: "computed.n1899da0e-5d7a.n836a3219-01ab@1",
        title: "Output of node n836a321",
      },
    ]);
  });

  it("labels a hub dataset input by its last id segment", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({
        origin: "computed",
        upstreamInputs: [{ datasetId: "data.urbanlab.acs-neighborhood-profile" }],
      }),
      nodes: [],
    });
    expect(upstream.sourceDatasets).toEqual([
      {
        datasetId: "data.urbanlab.acs-neighborhood-profile",
        title: "acs-neighborhood-profile",
      },
    ]);
  });

  it("splits node and dataset inputs and de-duplicates each", () => {
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({
        origin: "computed",
        upstreamInputs: [
          { nodeId: "feeder-1", nodeType: "DATA_LOADING" },
          { nodeId: "feeder-1", nodeType: "DATA_LOADING" },
          { datasetId: "data.a" },
          { datasetId: "data.a" },
          {},
        ],
      }),
      nodes: [],
    });
    expect(upstream.inputNodes?.map((n) => n.nodeId)).toEqual(["feeder-1"]);
    expect(upstream.sourceDatasets.map((d) => d.datasetId)).toEqual(["data.a"]);
  });

  it("has no inputs for a dataset that records none", () => {
    // Every imported dataset, and any computed one saved before the lineage
    // fields existed.
    const upstream = selectDatasetUpstreamLineage({
      dataset: catalogItem({ origin: "hub" }),
      nodes: [],
    });
    expect(upstream.inputNodes).toEqual([]);
    expect(upstream.sourceDatasets).toEqual([]);
  });
});

describe("selectDatasetLineage", () => {
  it("flags unresolved references as partial lineage", () => {
    const lineage = selectDatasetLineage({
      dataset: catalogItem({ consumerNodeIds: ["ghost-node"] }),
      nodes: [],
    });
    expect(lineage.status.hasUnresolvedReferences).toBe(true);
    expect(lineage.status.isPartial).toBe(true);
  });

  it("flags missing canvas context as partial lineage", () => {
    const lineage = selectDatasetLineage({
      dataset: catalogItem(),
      nodes: [],
      canvasAvailable: false,
    });
    expect(lineage.status.hasUnresolvedReferences).toBe(false);
    expect(lineage.status.isPartial).toBe(true);
  });

  it("reports clean lineage for a fully resolved canvas", () => {
    const lineage = selectDatasetLineage({
      dataset: catalogItem(),
      nodes: [canvasNode({ datasetRefs: [DATASET_ID] })],
    });
    expect(lineage.status.hasLineage).toBe(true);
    expect(lineage.status.hasUnresolvedReferences).toBe(false);
    expect(lineage.status.isPartial).toBe(false);
  });

  it("reports hasLineage false for an unused imported dataset", () => {
    const lineage = selectDatasetLineage({ dataset: catalogItem(), nodes: [] });
    expect(lineage.status.hasLineage).toBe(false);
  });

  it("includes graph-connected consumers of a computed dataset end-to-end (#141)", () => {
    const lineage = selectDatasetLineage({
      dataset: catalogItem({ origin: "computed", producerNodeId: "node-1" }),
      nodes: [
        canvasNode({ nodeId: "node-1", nodeType: "PYTHON_COMPUTATION" }),
        canvasNode({ nodeId: "node-2", nodeType: "VEGA" }),
      ],
      edges: [{ source: "node-1", target: "node-2" }],
    });
    expect(lineage.downstream.consumingNodes.map((n) => n.nodeId)).toContain("node-2");
    expect(lineage.status.hasLineage).toBe(true);
  });
});

describe("formatting helpers", () => {
  it("formats raw node type ids", () => {
    expect(formatNodeTypeLabel("DATA_LOADING")).toBe("Data Loading");
    expect(formatNodeTypeLabel("pkg:spatial-filter")).toBe("Spatial Filter");
    expect(formatNodeTypeLabel(undefined)).toBe("Node");
  });

  it("drops the package path and version from a qualified node type", () => {
    // What the canvas actually stores for a builtin node. Printed raw the badge
    // read "CURIO.BUILTIN/DATA TRANSFORMATION@1" - the package and the version
    // are addressing detail, and the type is the only part worth showing.
    expect(formatNodeTypeLabel("curio.builtin/data-transformation@1")).toBe(
      "Data Transformation",
    );
    expect(formatNodeTypeLabel("curio.builtin/data-transformation")).toBe(
      "Data Transformation",
    );
    expect(formatNodeTypeLabel("acme.geo/spatial_join@12")).toBe("Spatial Join");
  });

  it("summarizes usage counts", () => {
    expect(
      lineageUsageSummary({
        consumingNodes: [],
        consumingDataflows: [],
        derivedDatasets: [],
      }),
    ).toBe("No nodes or dataflows are currently using this dataset.");

    const usage = selectDatasetDownstreamUsage({
      datasetId: DATASET_ID,
      dataflowId: "flow-1",
      nodes: [
        canvasNode({ nodeId: "node-1", datasetRefs: [DATASET_ID] }),
        canvasNode({ nodeId: "node-2", datasetRefs: [DATASET_ID] }),
      ],
    });
    expect(lineageUsageSummary(usage)).toBe("Used by 2 nodes in 1 dataflow");
  });

  it("builds the upstream origin caption", () => {
    expect(upstreamOriginCaption(catalogItem({ origin: "hub", format: "geojson" }))).toBe(
      "Imported · GeoJSON",
    );
  });
});

describe("lineageNodesFromDataflowUsage (canvas-less fallback)", () => {
  it("flattens backend usage into active downstream node usages", () => {
    const usage: DatasetDataflowUsageRef[] = [
      {
        dataflowId: "flow-1",
        dataflowName: "Flow One",
        nodeCount: 2,
        nodes: [
          { nodeId: "node-a", nodeType: "DATA_TRANSFORMATION" },
          { nodeId: "node-b", nodeType: "VIS_VEGA" },
        ],
      },
    ];
    const nodes = lineageNodesFromDataflowUsage(usage);
    expect(nodes).toHaveLength(2);
    expect(nodes[0]).toMatchObject({
      nodeId: "node-a",
      nodeType: "DATA_TRANSFORMATION",
      dataflowId: "flow-1",
      dataflowName: "Flow One",
      usageType: "input",
      status: "active",
    });
  });

  it("returns nothing when no dataflow lists consumer nodes", () => {
    const usage: DatasetDataflowUsageRef[] = [
      { dataflowId: "flow-1", dataflowName: "Producer only", nodeCount: 0 },
    ];
    expect(lineageNodesFromDataflowUsage(usage)).toEqual([]);
    expect(lineageNodesFromDataflowUsage([])).toEqual([]);
  });

  it("builds a downstream view with both nodes and dataflows, so the summary reads correctly", () => {
    const usage: DatasetDataflowUsageRef[] = [
      {
        dataflowId: "flow-1",
        dataflowName: "Flow One",
        nodeCount: 2,
        nodes: [
          { nodeId: "node-a", nodeType: "DATA_TRANSFORMATION" },
          { nodeId: "node-b", nodeType: "VIS_VEGA" },
        ],
      },
      // A dataflow that only produced the dataset (no consumer nodes) is not counted.
      { dataflowId: "flow-2", dataflowName: "Producer only", nodeCount: 0 },
    ];
    const downstream = downstreamFromDataflowUsage(usage);
    expect(downstream.consumingNodes).toHaveLength(2);
    expect(downstream.consumingDataflows).toHaveLength(1);
    expect(downstream.consumingDataflows[0]).toMatchObject({
      dataflowId: "flow-1",
      nodeIds: ["node-a", "node-b"],
      usageCount: 2,
      status: "active",
    });
    expect(lineageUsageSummary(downstream)).toBe("Used by 2 nodes in 1 dataflow");
  });
});
