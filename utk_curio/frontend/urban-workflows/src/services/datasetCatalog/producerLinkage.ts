import { DatasetCatalogItem } from "./datasetCatalogTypes";

/**
 * Map a producer node id → the persisted computed dataset it generated.
 *
 * This is the *producer* half of the canvas↔palette linkage: unlike the consumer
 * marker (``datasetSource`` stamped on palette-created loader nodes), producer
 * linkage is **derived** from the live catalog so the node chip appears/disappears
 * with the dataset itself and never goes stale. Match key is ``producerNodeId``
 * (the canvas node id), which is stable across re-executions even though the
 * output filename/path changes.
 *
 * A computed dataset qualifies once it is PERSISTED: either installed into the
 * open dataflow (``installed === true`` — a spec ref exists) or saved to the
 * account store (``dirName`` set — computed outputs are account-level assets on
 * save, with no ref until an explicit Install, #175). Ephemeral session-only
 * outputs (no ref, no store dir) are excluded. When a single node produced more
 * than one matching item, the first wins (callers query with ``sort: "recent"``).
 */
/**
 * Whether *item* is an output a node of dataflow *dataflowId* saved to the
 * account store (#217). Matched on the producing dataflow, which the store
 * manifest records, or on the dataflow-namespaced id
 * (``computed.<dataflowId>.<nodeId>``). Never on the bare ``producerNodeId``:
 * node ids recur across dataflows (#168).
 */
export function isSavedOutputOfDataflow(
  item: DatasetCatalogItem,
  dataflowId: string | null | undefined,
): boolean {
  if (!dataflowId || item.origin !== "computed" || !item.dirName) return false;
  if (item.producerDataflowId) return item.producerDataflowId === dataflowId;
  return item.id.startsWith(`computed.${dataflowId}.`);
}

export function installedComputedByProducer(
  items: DatasetCatalogItem[],
): Map<string, DatasetCatalogItem> {
  const map = new Map<string, DatasetCatalogItem>();
  for (const item of items) {
    if (
      item.origin === "computed" &&
      (item.installed === true || Boolean(item.dirName)) &&
      item.producerNodeId &&
      !map.has(item.producerNodeId)
    ) {
      map.set(item.producerNodeId, item);
    }
  }
  return map;
}
