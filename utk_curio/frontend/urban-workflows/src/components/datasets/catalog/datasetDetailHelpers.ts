import {
  DATASET_ORIGIN_LABEL,
  DatasetCatalogItem,
  DatasetFormat,
  datasetListSourceCaption,
} from "../../../services/datasetCatalog";

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

export function datasetCount(dataset?: DatasetCatalogItem | null): string | null {
  if (!dataset) return null;
  if (dataset.featureCount != null) return `${dataset.featureCount.toLocaleString()} features`;
  if (dataset.rowCount != null) return `${dataset.rowCount.toLocaleString()} rows`;
  return null;
}

export function datasetIconVariant(dataset: DatasetCatalogItem): "mint" | "sky" | "lilac" {
  let hash = 0;
  for (let i = 0; i < dataset.id.length; i++) {
    hash = (hash + dataset.id.charCodeAt(i)) % 3;
  }
  return hash === 0 ? "mint" : hash === 1 ? "sky" : "lilac";
}

export function datasetInitials(title: string): string {
  const words = title.trim().split(/\s+/).filter(Boolean);
  const seed = words.length > 1 ? `${words[0][0]}${words[1][0]}` : title.slice(0, 2);
  return seed.toUpperCase();
}

export function formatDatasetLocation(dataset: DatasetCatalogItem): string {
  const caption = datasetListSourceCaption(dataset);
  if (caption) return caption;
  return dataset.path || dataset.uri || DATASET_ORIGIN_LABEL[dataset.origin];
}

export function formatClass(format: DatasetFormat, styles: Record<string, string>): string {
  return `${styles.formatChip} ${styles[`format_${format}`] || ""}`;
}
