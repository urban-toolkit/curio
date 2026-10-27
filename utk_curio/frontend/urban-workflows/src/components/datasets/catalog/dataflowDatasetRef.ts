import type { Dispatch, SetStateAction } from "react";
import {
  datasetCatalogApi,
  isLayerGroupId,
  notifyDatasetCatalogRefresh,
  type DatasetCatalogItem,
} from "../../../services/datasetCatalog";

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

/**
 * Add *dataset* to the dataflow *dataflowId*, as the Data Catalog's Add to
 * project does, and to the dataflow's palette refs (*setDataflowDatasets*).
 * A layer group's id is synthetic, so each of its real layers is added, which
 * keeps the dataflow's refs (and the saved spec) accurate. *title* names a
 * computed dataset's copy. One refresh event then reaches every catalog
 * listener. Returns the datasets added.
 */
export async function addDatasetToDataflow(
  dataflowId: string,
  dataset: DatasetCatalogItem,
  setDataflowDatasets: Dispatch<SetStateAction<any[]>>,
  title?: string,
): Promise<DatasetCatalogItem[]> {
  const isGroup = isLayerGroupId(dataset.id);
  const memberIds = isGroup ? dataset.groupLayerIds ?? [] : [dataset.id];
  const installedItems: DatasetCatalogItem[] = [];
  for (const memberId of memberIds) {
    installedItems.push(
      await datasetCatalogApi.installToDataflow(
        dataflowId,
        memberId,
        isGroup ? undefined : dataset,
        isGroup ? undefined : title,
      ),
    );
  }
  setDataflowDatasets((prev) => {
    const installedIds = new Set(installedItems.map((it) => it.id));
    const next = prev.filter((row) => !installedIds.has(String(row?.datasetId || row?.id)));
    return [...next, ...installedItems.map(dataflowRefFromCatalogItem)];
  });
  // One refresh event fans out to every catalog listener, the drawer's own
  // included, which does the bust-cache reload (#178).
  notifyDatasetCatalogRefresh();
  return installedItems;
}
