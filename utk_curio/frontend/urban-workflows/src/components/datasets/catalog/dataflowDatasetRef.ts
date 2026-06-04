import type { DatasetCatalogItem } from "../../../services/datasetCatalog";

/** Lean or legacy dataflow ref for an installed/imported dataset. */
export function dataflowRefFromCatalogItem(
  installed: DatasetCatalogItem,
): Record<string, unknown> {
  const installedAt = new Date().toISOString();
  if (installed.dirName) {
    return {
      datasetId: installed.id,
      dirName: installed.dirName,
      origin: installed.origin,
      ...(installed.producerNodeId ? { producerNodeId: installed.producerNodeId } : {}),
      installedAt,
    };
  }
  return {
    datasetId: installed.id,
    title: installed.title,
    description: installed.description,
    origin: installed.origin,
    uri: installed.uri,
    path: installed.path,
    format: installed.format,
    sizeBytes: installed.sizeBytes,
    rowCount: installed.rowCount,
    featureCount: installed.featureCount,
    sourceLabel: installed.sourceLabel,
    tags: installed.tags,
    updatedAt: installed.updatedAt,
    installedAt,
  };
}
