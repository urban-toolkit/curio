import type { DatasetCatalogItem } from "../../services/datasetCatalog";
import {
  datasetCountCompact,
  formatBytes,
  relativeTime,
} from "../../components/datasets/catalog/datasetDetailHelpers";

// Re-export the shared catalog helpers so data-hub callers keep importing them
// from here, but there is a single implementation. ``datasetCount`` uses the
// compact (``"feat."``) variant the browse rows have always rendered.
export { formatBytes, relativeTime };
export const datasetCount = datasetCountCompact;

export function isFresh(iso?: string | null): boolean {
  if (!iso) return false;
  const delta = Date.now() - new Date(iso).getTime();
  return Number.isFinite(delta) && delta < 24 * 60 * 60 * 1000;
}

export function metaLeft(dataset: DatasetCatalogItem): string {
  return [
    datasetCount(dataset),
    formatBytes(dataset.sizeBytes),
    `${dataset.consumerNodeIds.length} nodes consume`,
  ]
    .filter(Boolean)
    .join(" | ");
}
