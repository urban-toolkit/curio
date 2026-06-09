import { useContext, useMemo } from "react";
import { FlowContext } from "../../providers/FlowProvider";
import { tryGetNodeDescriptor } from "../../registry/nodeRegistry";
import type { DatasetCatalogItem } from "../datasetCatalog";
import {
  LineageCanvasNode,
  selectDatasetLineage,
} from "./datasetLineageResolver";
import type { DatasetLineage } from "./datasetLineageTypes";

function registryNodeLabel(nodeType: string | undefined): string | undefined {
  if (!nodeType) return undefined;
  return tryGetNodeDescriptor(nodeType)?.label;
}

export interface UseDatasetLineageOptions {
  dataflowId?: string | null;
  /**
   * False when the panel is rendered without a canvas (standalone catalog
   * page), so live usage cannot be resolved and lineage is flagged partial.
   */
  canvasAvailable?: boolean;
}

/**
 * Live dataset lineage derived from the current canvas state. Recomputes
 * whenever nodes, their dataset bindings, or execution status change.
 * Safe to call outside `FlowProvider` (falls back to an empty canvas).
 */
export function useDatasetLineage(
  dataset: DatasetCatalogItem | null,
  options: UseDatasetLineageOptions = {},
): DatasetLineage | null {
  const { dataflowId = null, canvasAvailable = true } = options;
  const { nodes, nodeExecStatus, projectName, workflowNameRef } =
    useContext(FlowContext);

  return useMemo(() => {
    if (!dataset) return null;
    return selectDatasetLineage({
      dataset,
      nodes: (nodes || []) as LineageCanvasNode[],
      dataflowId,
      dataflowName: projectName || workflowNameRef?.current || null,
      nodeExecStatus,
      resolveNodeLabel: registryNodeLabel,
      canvasAvailable,
    });
  }, [dataset, nodes, nodeExecStatus, dataflowId, projectName, workflowNameRef, canvasAvailable]);
}
