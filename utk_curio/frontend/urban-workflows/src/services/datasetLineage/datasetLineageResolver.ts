/**
 * Dataset lineage resolver — pure selectors over the live canvas state.
 *
 * Downstream usage is derived from each node's dataset bindings
 * (``data.datasetRefs`` / ``data.appliedDatasets``, set by drag-drop in
 * ``datasetApplication.ts`` and persisted by ``TrillGenerator``). Nothing here
 * persists anything: lineage is a read-only view, so
 * ``CURIO_DEFAULT_SAVE_NODE_OUTPUT=false`` is never bypassed.
 */
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetProvenanceLabel,
} from "../datasetCatalog";
import {
  DatasetDownstreamUsage,
  DatasetLineage,
  DatasetLineageDataflowUsageRef,
  DatasetLineageNodeUsageRef,
  DatasetUpstreamLineage,
  LineageStatus,
} from "./datasetLineageTypes";

/** Minimal shape of a canvas node the resolver needs (subset of ReactFlow INode). */
export interface LineageCanvasNode {
  data?: {
    nodeId?: string;
    nodeType?: string;
    templateName?: string;
    datasetRefs?: string[];
    appliedDatasets?: Record<
      string,
      { id?: string; datasetId?: string; title?: string } | null | undefined
    > | null;
  } | null;
}

export type NodeExecStatusMap = Record<string, "stale" | "executed">;

export type NodeLabelResolver = (nodeType: string | undefined) => string | undefined;

/** Fallback prettifier for raw node type ids (e.g. "DATA_LOADING" → "Data Loading"). */
export function formatNodeTypeLabel(nodeType: string | undefined): string {
  if (!nodeType) return "Node";
  const cleaned = nodeType
    .replace(/^[^:]*:/, "")
    .replace(/[_-]+/g, " ")
    .trim();
  if (!cleaned) return "Node";
  return cleaned
    .split(/\s+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

/** All dataset ids referenced by a node (datasetRefs ∪ appliedDatasets keys/values). */
function datasetIdsForNode(node: LineageCanvasNode): Set<string> {
  const ids = new Set<string>();
  const data = node?.data;
  if (!data) return ids;
  for (const ref of data.datasetRefs || []) {
    if (typeof ref === "string" && ref) ids.add(ref);
  }
  const applied = data.appliedDatasets || {};
  for (const [key, value] of Object.entries(applied)) {
    if (key) ids.add(key);
    const valueId = value?.datasetId || value?.id;
    if (valueId) ids.add(valueId);
  }
  return ids;
}

export interface DownstreamUsageParams {
  datasetId: string;
  nodes: LineageCanvasNode[];
  dataflowId?: string | null;
  dataflowName?: string | null;
  /** Consumer node ids persisted on the dataset ref (may reference removed nodes). */
  persistedConsumerNodeIds?: string[];
  nodeExecStatus?: NodeExecStatusMap;
  resolveNodeLabel?: NodeLabelResolver;
}

/**
 * Given a dataset id, find all canvas nodes whose inputs reference it and
 * group them by dataflow. Persisted consumer ids that no longer match a
 * canvas node are reported with status "unresolved".
 */
export function selectDatasetDownstreamUsage(
  params: DownstreamUsageParams,
): DatasetDownstreamUsage {
  const {
    datasetId,
    nodes,
    dataflowId = null,
    dataflowName = null,
    persistedConsumerNodeIds = [],
    nodeExecStatus = {},
    resolveNodeLabel,
  } = params;

  const consumingNodes: DatasetLineageNodeUsageRef[] = [];
  const seenNodeIds = new Set<string>();

  for (const node of nodes || []) {
    const nodeId = node?.data?.nodeId;
    if (!nodeId || seenNodeIds.has(nodeId)) continue;
    if (!datasetIdsForNode(node).has(datasetId)) continue;
    seenNodeIds.add(nodeId);

    const nodeType = node.data?.nodeType;
    const status: LineageStatus =
      nodeExecStatus[nodeId] === "stale" ? "stale" : "active";
    consumingNodes.push({
      nodeId,
      nodeName:
        resolveNodeLabel?.(nodeType) ||
        node.data?.templateName ||
        formatNodeTypeLabel(nodeType),
      nodeType,
      dataflowId,
      dataflowName,
      usageType: node.data?.appliedDatasets?.[datasetId] ? "input" : "parameter",
      status,
    });
  }

  for (const persistedId of persistedConsumerNodeIds) {
    if (!persistedId || seenNodeIds.has(persistedId)) continue;
    seenNodeIds.add(persistedId);
    consumingNodes.push({
      nodeId: persistedId,
      nodeName: undefined,
      nodeType: undefined,
      dataflowId,
      dataflowName,
      usageType: "unknown",
      status: "unresolved",
    });
  }

  const byDataflow = new Map<string, DatasetLineageNodeUsageRef[]>();
  for (const usage of consumingNodes) {
    const key = usage.dataflowId || "__current__";
    const bucket = byDataflow.get(key) || [];
    bucket.push(usage);
    byDataflow.set(key, bucket);
  }

  const consumingDataflows: DatasetLineageDataflowUsageRef[] = Array.from(
    byDataflow.entries(),
  ).map(([key, usages]) => ({
    dataflowId: key,
    dataflowName: usages[0]?.dataflowName ?? null,
    nodeIds: usages.map((usage) => usage.nodeId),
    usageCount: usages.length,
    status: usages.some((usage) => usage.status === "unresolved")
      ? "unresolved"
      : usages.some((usage) => usage.status === "stale")
        ? "stale"
        : "active",
  }));

  return { consumingNodes, consumingDataflows, derivedDatasets: [] };
}

export interface UpstreamLineageParams {
  dataset: Pick<DatasetCatalogItem, "origin" | "format" | "producerNodeId">;
  nodes: LineageCanvasNode[];
  resolveNodeLabel?: NodeLabelResolver;
}

/** Resolve what generated the dataset: producer node (computed) or import origin. */
export function selectDatasetUpstreamLineage(
  params: UpstreamLineageParams,
): DatasetUpstreamLineage {
  const { dataset, nodes, resolveNodeLabel } = params;
  const producerNodeId = dataset.producerNodeId || null;

  let generatingNode: DatasetUpstreamLineage["generatingNode"] = null;
  if (producerNodeId) {
    const producer = (nodes || []).find(
      (node) => node?.data?.nodeId === producerNodeId,
    );
    const nodeType = producer?.data?.nodeType;
    generatingNode = {
      nodeId: producerNodeId,
      nodeName: producer
        ? resolveNodeLabel?.(nodeType) ||
          producer.data?.templateName ||
          formatNodeTypeLabel(nodeType)
        : undefined,
      nodeType,
    };
  }

  return {
    generatingNode,
    sourceDatasets: [],
    origin: dataset.origin,
    originLabel: datasetProvenanceLabel(dataset.origin),
  };
}

export interface DatasetLineageParams {
  dataset: DatasetCatalogItem;
  nodes: LineageCanvasNode[];
  dataflowId?: string | null;
  dataflowName?: string | null;
  nodeExecStatus?: NodeExecStatusMap;
  resolveNodeLabel?: NodeLabelResolver;
  /**
   * False when no canvas/dataflow context is mounted (e.g. the standalone
   * catalog page), so usage outside the current view cannot be resolved.
   */
  canvasAvailable?: boolean;
}

export function selectDatasetLineage(params: DatasetLineageParams): DatasetLineage {
  const {
    dataset,
    nodes,
    dataflowId = null,
    dataflowName = null,
    nodeExecStatus,
    resolveNodeLabel,
    canvasAvailable = true,
  } = params;

  const downstream = selectDatasetDownstreamUsage({
    datasetId: dataset.id,
    nodes,
    dataflowId,
    dataflowName,
    persistedConsumerNodeIds: dataset.consumerNodeIds || [],
    nodeExecStatus,
    resolveNodeLabel,
  });
  const upstream = selectDatasetUpstreamLineage({ dataset, nodes, resolveNodeLabel });

  const hasUnresolvedReferences = downstream.consumingNodes.some(
    (usage) => usage.status === "unresolved",
  );

  return {
    datasetId: dataset.id,
    upstream,
    downstream,
    status: {
      hasLineage:
        downstream.consumingNodes.length > 0 || upstream.generatingNode != null,
      hasUnresolvedReferences,
      isPartial: hasUnresolvedReferences || !canvasAvailable,
      lastComputedAt: new Date().toISOString(),
    },
  };
}

/** Compact summary line for the Dataset Detail sidebar. */
export function lineageUsageSummary(downstream: DatasetDownstreamUsage): string {
  const nodeCount = downstream.consumingNodes.length;
  if (nodeCount === 0) {
    return "No nodes or dataflows are currently using this dataset.";
  }
  const flowCount = downstream.consumingDataflows.length;
  const nodeLabel = nodeCount === 1 ? "node" : "nodes";
  const flowLabel = flowCount === 1 ? "dataflow" : "dataflows";
  return `Used by ${nodeCount} ${nodeLabel} in ${flowCount} ${flowLabel}`;
}

/** Caption for the upstream/origin card. */
export function upstreamOriginCaption(
  dataset: Pick<DatasetCatalogItem, "origin" | "format">,
): string {
  const formatLabel = DATASET_FORMAT_LABEL[dataset.format] || dataset.format;
  return `${datasetProvenanceLabel(dataset.origin)} · ${formatLabel}`;
}
