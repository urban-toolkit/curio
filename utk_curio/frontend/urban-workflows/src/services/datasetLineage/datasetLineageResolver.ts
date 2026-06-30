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
  DatasetDataflowUsageRef,
  datasetProvenanceLabel,
} from "../datasetCatalog";
import {
  DatasetDownstreamUsage,
  DatasetLineage,
  DatasetLineageDataflowUsageRef,
  DatasetLineageNodeUsageRef,
  DatasetUpstreamLineage,
  LineageStatus,
  LineageUsageType,
} from "./datasetLineageTypes";

/** Minimal shape of a canvas node the resolver needs (subset of ReactFlow INode). */
export interface LineageCanvasNode {
  /** ReactFlow node id (used for edge matching); usually equal to data.nodeId. */
  id?: string;
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

/** Minimal shape of a canvas edge the resolver needs (subset of ReactFlow Edge). */
export interface LineageCanvasEdge {
  source?: string | null;
  target?: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
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

/**
 * Convert the backend cross-dataflow usage (``GET /datasets/<id>/usage``) into
 * downstream node usages. Used as a fallback on canvas-less surfaces (the
 * standalone catalog/browse page), where live lineage resolves no nodes because
 * there is no open canvas — the backend resolves consumers from saved specs.
 * References are treated as ``active``: they exist in persisted dataflows.
 */
export function lineageNodesFromDataflowUsage(
  usage: DatasetDataflowUsageRef[],
): DatasetLineageNodeUsageRef[] {
  const nodes: DatasetLineageNodeUsageRef[] = [];
  for (const flow of usage) {
    for (const node of flow.nodes ?? []) {
      nodes.push({
        nodeId: node.nodeId,
        nodeType: node.nodeType ?? undefined,
        dataflowId: flow.dataflowId,
        dataflowName: flow.dataflowName ?? null,
        usageType: "input",
        status: "active",
      });
    }
  }
  return nodes;
}

/**
 * Build a full downstream-usage view from the backend cross-dataflow usage, so
 * the canvas-less fallback populates BOTH the consumer nodes and the consuming
 * dataflows (otherwise the summary reads "Used by N nodes in 0 dataflows").
 * Only dataflows that actually list consumer nodes count as consuming.
 */
export function downstreamFromDataflowUsage(
  usage: DatasetDataflowUsageRef[],
): DatasetDownstreamUsage {
  const consumingDataflows: DatasetLineageDataflowUsageRef[] = usage
    .filter((flow) => (flow.nodes?.length ?? 0) > 0)
    .map((flow) => ({
      dataflowId: flow.dataflowId,
      dataflowName: flow.dataflowName ?? null,
      nodeIds: (flow.nodes ?? []).map((node) => node.nodeId),
      usageCount: flow.nodes?.length ?? 0,
      status: "active",
    }));
  return {
    consumingNodes: lineageNodesFromDataflowUsage(usage),
    consumingDataflows,
    derivedDatasets: [],
  };
}

/** True for a Data Loading node (``curio.builtin/data-loading`` or the legacy
 * ``DATA_LOADING``) — the node a dataset drag-drop creates. It is the dataset's
 * *source* in the flow, not a downstream consumer of it. */
function isDataLoadingNodeType(nodeType: string | undefined): boolean {
  if (!nodeType) return false;
  return nodeType === "DATA_LOADING" || nodeType.includes("data-loading");
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
  /** Canvas edges — used to resolve graph-connected consumers of a computed dataset. */
  edges?: LineageCanvasEdge[];
  /**
   * Producer node of a computed dataset. Its directly-connected downstream
   * nodes consume the dataset through ``data.input`` (a graph edge), not through
   * a ``datasetRefs``/``appliedDatasets`` binding, so they must be resolved from
   * ``edges`` rather than node bindings.
   */
  producerNodeId?: string | null;
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
    edges = [],
    producerNodeId = null,
  } = params;

  const consumingNodes: DatasetLineageNodeUsageRef[] = [];
  const seenNodeIds = new Set<string>();

  const nodeId_ = (node: LineageCanvasNode): string | undefined =>
    node?.data?.nodeId ?? node?.id ?? undefined;
  const describeConsumer = (
    targetId: string,
    node: LineageCanvasNode | undefined,
    usageType: LineageUsageType,
  ): DatasetLineageNodeUsageRef => {
    const nodeType = node?.data?.nodeType;
    return {
      nodeId: targetId,
      nodeName: node
        ? resolveNodeLabel?.(nodeType) ||
          node.data?.templateName ||
          formatNodeTypeLabel(nodeType)
        : undefined,
      nodeType,
      dataflowId,
      dataflowName,
      usageType,
      status: nodeExecStatus[targetId] === "stale" ? "stale" : "active",
    };
  };

  for (const node of nodes || []) {
    const nodeId = node?.data?.nodeId;
    if (!nodeId || seenNodeIds.has(nodeId)) continue;
    if (!datasetIdsForNode(node).has(datasetId)) continue;
    // A Data Loading node that references the dataset is the dataset's source
    // (its "box" dropped on the canvas), not a downstream consumer. Skip it —
    // dropping a loader must not, on its own, register a downstream usage. Its
    // real consumers are the nodes wired to its output (the carrier pass below).
    if (isDataLoadingNodeType(node.data?.nodeType)) continue;
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

  // The dataset enters the flow through "carrier" nodes — the computed
  // producer and any Data Loading node that (re)loads it — and is *consumed* by
  // the nodes wired directly downstream of those carriers (they read it via
  // ``data.input``, a graph edge, not a dataset binding). Resolving consumers
  // from edges (not from the carrier's own binding) means a freshly-dropped,
  // unconnected loader registers no downstream usage, while connecting it later
  // surfaces its real consumers (#141 / computed-dataset downstream item).
  const carrierIds = new Set<string>();
  if (producerNodeId) carrierIds.add(producerNodeId);
  const nodeById = new Map<string, LineageCanvasNode>();
  for (const node of nodes || []) {
    const id = nodeId_(node);
    if (!id) continue;
    nodeById.set(id, node);
    if (isDataLoadingNodeType(node.data?.nodeType) && datasetIdsForNode(node).has(datasetId)) {
      carrierIds.add(id);
    }
  }
  if (carrierIds.size) {
    for (const edge of edges || []) {
      if (!edge || !edge.source || !carrierIds.has(edge.source)) continue;
      // Skip bidirectional interaction/sync edges — not data consumption.
      if (edge.sourceHandle === "in/out" && edge.targetHandle === "in/out") continue;
      const targetId = edge.target;
      if (!targetId || carrierIds.has(targetId) || seenNodeIds.has(targetId)) continue;
      seenNodeIds.add(targetId);
      consumingNodes.push(describeConsumer(targetId, nodeById.get(targetId), "input"));
    }
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

/**
 * The producing node id of a computed dataset, derived from the persisted
 * lineage data: an explicit ``producerNodeId`` when present, otherwise the node
 * id encoded in the dataset id/dirName (``computed.<sanitizedNodeId>[@N]``).
 *
 * Reinstalling a computed dataset from a previous node persists its ref with a
 * null ``producerNodeId`` (origin flips to "imported"), which would otherwise
 * drop the upstream connection badge in the catalog card/palette while the
 * detail sidebar — built from a producer-resolved item — still shows it. Both
 * surfaces resolve upstream through this helper, so the badge stays consistent
 * with the sidebar regardless of newly-generated / uninstalled / reinstalled
 * state.
 */
export function producerNodeIdForDataset(
  dataset: Pick<DatasetCatalogItem, "id" | "dirName" | "producerNodeId">,
): string | null {
  if (dataset.producerNodeId) return dataset.producerNodeId;
  const source = dataset.dirName || dataset.id || "";
  if (!source.startsWith("computed.")) return null;
  const seg = source.slice("computed.".length).replace(/@\d+$/, "");
  return seg || null;
}

export interface UpstreamLineageParams {
  dataset: Pick<
    DatasetCatalogItem,
    | "id"
    | "dirName"
    | "origin"
    | "format"
    | "producerNodeId"
    | "producerNodeType"
    | "producerDataflowId"
    | "producerDataflowName"
  >;
  nodes: LineageCanvasNode[];
  resolveNodeLabel?: NodeLabelResolver;
}

/** Resolve what generated the dataset: producer node (computed) or import origin. */
export function selectDatasetUpstreamLineage(
  params: UpstreamLineageParams,
): DatasetUpstreamLineage {
  const { dataset, nodes, resolveNodeLabel } = params;
  const producerNodeId = producerNodeIdForDataset(dataset);

  let generatingNode: DatasetUpstreamLineage["generatingNode"] = null;
  if (producerNodeId) {
    const producer = (nodes || []).find(
      (node) => node?.data?.nodeId === producerNodeId,
    );
    // Prefer the producer node on the open canvas. When it isn't here — the
    // dataset was opened from a dataflow that only imported it — fall back to
    // the producer type/dataflow resolved by the backend across the user's
    // projects, so the card still names the generating node and its dataflow
    // instead of a meaningless sliced id.
    const nodeType = producer?.data?.nodeType ?? dataset.producerNodeType ?? undefined;
    const nodeName = producer
      ? resolveNodeLabel?.(nodeType) ||
        producer.data?.templateName ||
        formatNodeTypeLabel(nodeType)
      : nodeType
        ? resolveNodeLabel?.(nodeType) || formatNodeTypeLabel(nodeType)
        : undefined;
    generatingNode = {
      nodeId: producerNodeId,
      nodeName,
      nodeType,
      // Surface the producing dataflow only when the producer is off-canvas
      // (cross-dataflow); on the producing canvas it's the current dataflow.
      dataflowId: producer ? null : dataset.producerDataflowId ?? null,
      dataflowName: producer ? null : dataset.producerDataflowName ?? null,
    };
  }

  return {
    generatingNode,
    sourceDatasets: [],
    origin: dataset.origin,
    originLabel: datasetProvenanceLabel(dataset.origin, dataset.format),
  };
}

export interface DatasetLineageParams {
  dataset: DatasetCatalogItem;
  nodes: LineageCanvasNode[];
  edges?: LineageCanvasEdge[];
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
    edges = [],
    dataflowId = null,
    dataflowName = null,
    nodeExecStatus,
    resolveNodeLabel,
    canvasAvailable = true,
  } = params;

  const downstream = selectDatasetDownstreamUsage({
    datasetId: dataset.id,
    nodes,
    edges,
    // Derive the producer from the computed id when the ref dropped it (reinstall),
    // so downstream carrier resolution matches a freshly-generated dataset.
    producerNodeId: producerNodeIdForDataset(dataset),
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
  return `${datasetProvenanceLabel(dataset.origin, dataset.format)} · ${formatLabel}`;
}
