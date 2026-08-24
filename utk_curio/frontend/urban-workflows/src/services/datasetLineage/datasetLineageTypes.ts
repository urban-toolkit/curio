import type { DatasetOrigin } from "../datasetCatalog";

export type LineageUsageType = "input" | "parameter" | "derived" | "unknown";

export type LineageStatus = "active" | "stale" | "missing" | "unresolved";

export interface DatasetLineageNodeRef {
  nodeId: string;
  nodeName?: string;
  nodeType?: string;
  /** Set only when the node lives in a different dataflow than the one the
   * details page was opened from (cross-dataflow producer). */
  dataflowId?: string | null;
  dataflowName?: string | null;
}

export interface DatasetLineageDatasetRef {
  datasetId: string;
  title?: string;
}

export interface DatasetLineageNodeUsageRef {
  nodeId: string;
  nodeName?: string;
  nodeType?: string;
  dataflowId?: string | null;
  dataflowName?: string | null;
  inputPortId?: string;
  inputPortName?: string;
  usageType: LineageUsageType;
  status: LineageStatus;
}

export interface DatasetLineageDataflowUsageRef {
  dataflowId: string;
  dataflowName?: string | null;
  nodeIds: string[];
  usageCount: number;
  status: LineageStatus;
}

export interface DatasetDownstreamUsage {
  consumingNodes: DatasetLineageNodeUsageRef[];
  consumingDataflows: DatasetLineageDataflowUsageRef[];
  /** Reserved for the derived-dataset phase of the lineage Epic. */
  derivedDatasets: DatasetLineageDatasetRef[];
}

export interface DatasetUpstreamLineage {
  /** Node that produced this dataset (from ``producerNodeId``), when known. */
  generatingNode?: DatasetLineageNodeRef | null;
  /** Datasets that fed the producing node, from the ``{datasetId}`` entries of
   * the dataset's persisted ``upstreamInputs``. */
  sourceDatasets: DatasetLineageDatasetRef[];
  /** Nodes that fed the producing node, from the ``{nodeId, nodeType}`` entries
   * of ``upstreamInputs``. Optional so a caller (or a test fixture) predating
   * the field still typechecks; treat a missing value as none. */
  inputNodes?: DatasetLineageNodeRef[];
  origin: DatasetOrigin;
  /** User-facing provenance label ("Imported" | "Computed"). */
  originLabel: string;
}

export interface DatasetLineageStatus {
  hasLineage: boolean;
  hasUnresolvedReferences: boolean;
  /** True when lineage could not be fully resolved (e.g. no canvas context). */
  isPartial: boolean;
  lastComputedAt?: string;
}

export interface DatasetLineage {
  datasetId: string;
  upstream: DatasetUpstreamLineage;
  downstream: DatasetDownstreamUsage;
  status: DatasetLineageStatus;
}
