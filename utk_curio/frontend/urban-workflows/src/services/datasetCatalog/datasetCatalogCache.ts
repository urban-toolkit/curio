import { DatasetCatalogResponse } from "./datasetCatalogTypes";

/**
 * Shared catalog response cache (drawer, palette, prefetch).
 *
 * One entry per fetch key (see ``catalogFetchKey``). Entries exist only to
 * hydrate the UI instantly (stale-while-revalidate) — every mutation
 * invalidates the WHOLE cache via {@link invalidateDatasetCatalogCache}
 * (called inside ``notifyDatasetCatalogRefresh``), so no surface can ever be
 * served a pre-mutation listing, mounted or not. Per-key busting is gone: it
 * left every *other* key stale after a mutation.
 */
const cache = new Map<string, DatasetCatalogResponse>();

/**
 * Bounds the ``liveOutputs``-driven key churn: every node execution mints a
 * new fetch key, and without eviction the map grew for the life of the page.
 */
const MAX_CACHE_ENTRIES = 16;

/**
 * Invalidation generation. A fetch that STARTED before an invalidation must
 * not repopulate the cache when it resolves after it (it may carry
 * pre-mutation data), so writers capture the epoch at fetch start and
 * {@link writeCatalogCache} drops the write on a mismatch.
 */
let epoch = 0;

export function catalogCacheEpoch(): number {
  return epoch;
}

/** Read an entry without subscribing. Refreshes the entry's LRU recency. */
export function peekCatalogCache(fetchKey: string): DatasetCatalogResponse | undefined {
  const hit = cache.get(fetchKey);
  if (hit !== undefined) {
    cache.delete(fetchKey);
    cache.set(fetchKey, hit);
  }
  return hit;
}

/**
 * Store a fetched response, unless the cache was invalidated after the fetch
 * started (``fetchEpoch`` mismatch). Returns whether the write was applied.
 * Evicts least-recently-used entries beyond {@link MAX_CACHE_ENTRIES}.
 */
export function writeCatalogCache(
  fetchKey: string,
  response: DatasetCatalogResponse,
  fetchEpoch: number,
): boolean {
  if (fetchEpoch !== epoch) return false;
  cache.delete(fetchKey);
  cache.set(fetchKey, response);
  while (cache.size > MAX_CACHE_ENTRIES) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
  return true;
}

/**
 * Drop every cached listing and bump the epoch so in-flight fetches cannot
 * write pre-invalidation data back. Called by ``notifyDatasetCatalogRefresh``
 * so invalidation happens even when no catalog surface is mounted.
 */
export function invalidateDatasetCatalogCache(): void {
  epoch += 1;
  cache.clear();
}

/** Current entry count — exposed for tests. */
export function catalogCacheSize(): number {
  return cache.size;
}
