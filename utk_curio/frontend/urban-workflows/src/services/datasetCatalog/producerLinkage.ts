import { DatasetCatalogItem } from "./datasetCatalogTypes";

/**
 * Map a producer node id → the installed computed dataset it generated.
 *
 * This is the *producer* half of the canvas↔palette linkage: unlike the consumer
 * marker (``datasetSource`` stamped on palette-created loader nodes), producer
 * linkage is **derived** from the live catalog so the node chip appears/disappears
 * with install/uninstall and never goes stale. Match key is ``producerNodeId``
 * (the canvas node id), which is stable across re-executions even though the
 * output filename/path changes.
 *
 * Only genuinely-installed computed datasets are linked (``installed === true``);
 * ephemeral session outputs are excluded. When a single node produced more than
 * one matching item, the first wins (callers query with ``sort: "recent"``).
 */
export function installedComputedByProducer(
  items: DatasetCatalogItem[],
): Map<string, DatasetCatalogItem> {
  const map = new Map<string, DatasetCatalogItem>();
  for (const item of items) {
    if (
      item.origin === "computed" &&
      item.installed === true &&
      item.producerNodeId &&
      !map.has(item.producerNodeId)
    ) {
      map.set(item.producerNodeId, item);
    }
  }
  return map;
}
