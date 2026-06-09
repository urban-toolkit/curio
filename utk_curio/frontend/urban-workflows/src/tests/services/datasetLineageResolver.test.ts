import {
  formatNodeTypeLabel,
  lineageUsageSummary,
  selectDatasetDownstreamUsage,
  selectDatasetLineage,
  selectDatasetUpstreamLineage,
  upstreamOriginCaption,
  type LineageCanvasNode,
} from "../../services/datasetLineage/datasetLineageResolver";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

const DATASET_ID = "ds-1";

function canvasNode(overrides: Partial<NonNullable<LineageCanvasNode["data"]>> = {}): LineageCanvasNode {
  return {
    data: {
      nodeId: "node-1",
      nodeType: "DATA_LOADING",
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
});

describe("formatting helpers", () => {
  it("formats raw node type ids", () => {
    expect(formatNodeTypeLabel("DATA_LOADING")).toBe("Data Loading");
    expect(formatNodeTypeLabel("pkg:spatial-filter")).toBe("Spatial Filter");
    expect(formatNodeTypeLabel(undefined)).toBe("Node");
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
