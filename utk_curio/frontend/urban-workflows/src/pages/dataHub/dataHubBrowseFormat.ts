import type { DatasetCatalogItem } from "../../services/datasetCatalog";

export function formatBytes(value?: number | null): string | null {
  if (value == null) return null;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function relativeTime(iso?: string | null): string {
  if (!iso) return "recently";
  const delta = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(delta)) return "recently";
  const minutes = Math.max(1, Math.round(delta / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function isFresh(iso?: string | null): boolean {
  if (!iso) return false;
  const delta = Date.now() - new Date(iso).getTime();
  return Number.isFinite(delta) && delta < 24 * 60 * 60 * 1000;
}

export function datasetCount(dataset?: DatasetCatalogItem | null): string | null {
  if (!dataset) return null;
  if (dataset.featureCount != null) return `${dataset.featureCount.toLocaleString()} feat.`;
  if (dataset.rowCount != null) return `${dataset.rowCount.toLocaleString()} rows`;
  return null;
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
