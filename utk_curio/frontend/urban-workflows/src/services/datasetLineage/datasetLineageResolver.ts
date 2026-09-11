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
  dataflowSegmentFromComputedId,
  nodeSegmentFromComputedId,
  sanitizeNodeIdSegment,
} from "../datasetCatalog/computedIds";
import {
  DatasetDownstreamUsage,
  DatasetLineage,
  DatasetLineageDataflowUsageRef,
  DatasetLineageDatasetRef,
  DatasetLineageNodeRef,
  DatasetLineageNodeUsageRef,
  DatasetUpstreamLineage,
  LineageStatus,
  LineageUsageType,
} from "./datasetLineageTypes";

/** Minimal shape of a canvas node the resolver needs (subset of ReactFlow INode). */
import { datasetIdsInCode } from "../datasetCatalog/datasetLoaderSnippets";

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
    /** Node source, scanned for ``curio_dataset_path`` references (#205). */
    code?: string;
    defaultCode?: string;
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

/**
 * Fallback prettifier for raw node type ids (e.g. "DATA_LOADING" → "Data
 * Loading"). Package-qualified, versioned ids reduce to the type alone
 * ("curio.builtin/data-transformation@1" → "Data Transformation"): the package
 * and version are addressing detail, not something to print in a badge.
 */
export function formatNodeTypeLabel(nodeType: string | undefined): string {
  if (!nodeType) return "Node";
  const cleaned = nodeType
    .replace(/^[^:]*:/, "")
    .replace(/@[^@/]*$/, "")
    .replace(/^.*\//, "")
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
  // Same blind spot the palette highlight had (#205): the bindings above exist
  // only on nodes created by dragging a dataset, so a hand-authored loader was
  // not recognised as a carrier and the edge walk below never reported its
  // downstream consumers.
  for (const id of datasetIdsInCode(data.code)) ids.add(id);
  for (const id of datasetIdsInCode(data.defaultCode)) ids.add(id);
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
 * lineage data: an explicit ``producerNodeId`` when present, otherwise the
 * NODE segment encoded in the dataset id/dirName
 * (``computed.[<dataflowSeg>.]<nodeSeg>[@N]`` — mirror of the backend
 * ``node_segment_from_computed_id``, #175). Never the full
 * ``<dataflowSeg>.<nodeSeg>`` pair a namespaced id carries: that string is not
 * a node id and both poisons carrier matching and leaks the dataflow UUID.
 *
 * When *options.nodes* is given, the sanitized segment is resolved to a REAL
 * canvas node id by sanitizing candidates (sanitization is not invertible).
 * When *options.dataflowId* is given, a namespaced id from ANOTHER dataflow
 * resolves to null — node ids recur across dataflows (Duplicate Project,
 * trill re-import), so a same-named node on this canvas is not the producer.
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
  options?: {
    nodes?: LineageCanvasNode[] | null;
    dataflowId?: string | null;
  },
): string | null {
  if (dataset.producerNodeId) return dataset.producerNodeId;
  const source = dataset.dirName || dataset.id || "";
  const nodeSeg = nodeSegmentFromComputedId(source);
  if (!nodeSeg) return null;
  const dfSeg = dataflowSegmentFromComputedId(source);
  const dataflowId = options?.dataflowId;
  if (dfSeg && dataflowId && sanitizeNodeIdSegment(dataflowId) !== dfSeg) {
    return null;
  }
  for (const node of options?.nodes || []) {
    const candidate = node?.data?.nodeId ?? node?.id;
    if (candidate && sanitizeNodeIdSegment(candidate) === nodeSeg) {
      return candidate;
    }
  }
  return nodeSeg;
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
    | "upstreamInputs"
  >;
  nodes: LineageCanvasNode[];
  /** Current canvas dataflow id — gates cross-dataflow producer attribution. */
  dataflowId?: string | null;
  resolveNodeLabel?: NodeLabelResolver;
}

/** Readable label for a dataset referenced only by id.
 *
 * A computed id is a pair of uuids (``computed.<dataflow>.<node>``), which is
 * unreadable in a card, so name it by its producing node the way the rest of
 * the lineage view names nodes. Anything else (a hub/imported id like
 * ``data.urbanlab.acs-neighborhood-profile``) reads fine as its last segment.
 */
export function sourceDatasetLabel(datasetId: string): string {
  const nodeSeg = nodeSegmentFromComputedId(datasetId);
  if (nodeSeg) return `Output of node ${nodeSeg.slice(0, 8)}`;
  const parts = datasetId.split(".");
  return parts[parts.length - 1] || datasetId;
}

/**
 * Split a dataset's persisted ``upstreamInputs`` into node refs and dataset
 * refs, naming each node against the open canvas where it is there.
 *
 * ``upstreamInputs`` is written by the installers when a node output is saved
 * (backend ``resolve_upstream_inputs``): one entry per incoming edge of the
 * producing node, plus one per dataset bound to it. Only computed datasets
 * carry any, so this is empty for everything imported.
 */
export function upstreamInputsFromDataset(
  dataset: Pick<DatasetCatalogItem, "upstreamInputs">,
  nodes: LineageCanvasNode[],
  resolveNodeLabel?: NodeLabelResolver,
): { inputNodes: DatasetLineageNodeRef[]; sourceDatasets: DatasetLineageDatasetRef[] } {
  const inputNodes: DatasetLineageNodeRef[] = [];
  const sourceDatasets: DatasetLineageDatasetRef[] = [];
  const seenNodes = new Set<string>();
  const seenDatasets = new Set<string>();

  for (const input of dataset?.upstreamInputs || []) {
    const datasetId = input?.datasetId;
    if (datasetId) {
      if (!seenDatasets.has(datasetId)) {
        seenDatasets.add(datasetId);
        sourceDatasets.push({ datasetId, title: sourceDatasetLabel(datasetId) });
      }
      // An entry is a node ref OR a dataset ref, never both.
      continue;
    }
    const nodeId = input?.nodeId;
    if (!nodeId || seenNodes.has(nodeId)) continue;
    seenNodes.add(nodeId);
    const onCanvas = (nodes || []).find((node) => node?.data?.nodeId === nodeId);
    // Prefer the node as it exists on this canvas, then the type the manifest
    // recorded - so an input from a dataflow that isn't open, or from a node
    // since deleted, is still named instead of shown as a bare uuid.
    const nodeType = onCanvas?.data?.nodeType ?? input?.nodeType ?? undefined;
    inputNodes.push({
      nodeId,
      nodeName: nodeType
        ? resolveNodeLabel?.(nodeType) ||
          onCanvas?.data?.templateName ||
          formatNodeTypeLabel(nodeType)
        : onCanvas?.data?.templateName,
      nodeType,
    });
  }

  return { inputNodes, sourceDatasets };
}

/** Resolve what generated the dataset: producer node (computed) or import origin. */
export function selectDatasetUpstreamLineage(
  params: UpstreamLineageParams,
): DatasetUpstreamLineage {
  const { dataset, nodes, dataflowId, resolveNodeLabel } = params;
  const producerNodeId = producerNodeIdForDataset(dataset, { nodes, dataflowId });

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

  const { inputNodes, sourceDatasets } = upstreamInputsFromDataset(
    dataset,
    nodes,
    resolveNodeLabel,
  );

  return {
    generatingNode,
    sourceDatasets,
    inputNodes,
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
    // resolved against the canvas nodes so carrier matching uses a REAL node id.
    producerNodeId: producerNodeIdForDataset(dataset, { nodes, dataflowId }),
    dataflowId,
    dataflowName,
    persistedConsumerNodeIds: dataset.consumerNodeIds || [],
    nodeExecStatus,
    resolveNodeLabel,
  });
  const upstream = selectDatasetUpstreamLineage({ dataset, nodes, dataflowId, resolveNodeLabel });

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
