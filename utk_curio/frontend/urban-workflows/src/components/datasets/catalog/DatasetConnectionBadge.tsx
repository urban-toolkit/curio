import React from "react";
import { DatasetCatalogItem } from "../../../services/datasetCatalog";
import { useDatasetLineage } from "../../../services/datasetLineage";

export interface DatasetConnectionCounts {
  /** 1 when the dataset has a producer (upstream) node, else 0. */
  upCount: number;
  /** Number of downstream consumer nodes. */
  downCount: number;
  hasConnections: boolean;
}

/**
 * Producer/consumer connection counts derived from the live lineage — the
 * single source the dataset palette row and the catalog card both render as a
 * connection badge.
 */
export function useDatasetConnectionCounts(
  dataset: DatasetCatalogItem | null,
): DatasetConnectionCounts {
  const lineage = useDatasetLineage(dataset);
  const upCount = lineage?.upstream.generatingNode ? 1 : 0;
  const downCount = lineage?.downstream.consumingNodes.length ?? 0;
  return { upCount, downCount, hasConnections: upCount > 0 || downCount > 0 };
}

/**
 * Compact up/down arrow badge of a dataset's upstream-producer /
 * downstream-consumer counts (e.g. "1↑ 2↓"). Renders nothing when the
 * dataset has no connections. ``className`` is supplied by the host so the badge
 * picks up that surface's styling.
 */
export const DatasetConnectionBadge: React.FC<{
  dataset: DatasetCatalogItem;
  className?: string;
}> = ({ dataset, className }) => {
  const { upCount, downCount, hasConnections } = useDatasetConnectionCounts(dataset);
  if (!hasConnections) return null;
  const label = [
    upCount > 0 ? `${upCount}↑` : "",
    downCount > 0 ? `${downCount}↓` : "",
  ]
    .filter(Boolean)
    .join(" ");
  return <span className={className}>{label}</span>;
};
