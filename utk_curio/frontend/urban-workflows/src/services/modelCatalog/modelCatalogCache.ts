import type { ModelCatalogResponse } from "./modelCatalogTypes";

/**
 * Cache for the model listing, one entry per search text.
 *
 * The listing reads a handful of manifests from disk, so caching it costs
 * nothing and makes a tab switch, or the drawer opening, instant.
 *
 * Epoch-based invalidation, matching `discoveryCatalogCache`: a fetch that
 * STARTED before an invalidation must not repopulate the cache when it resolves
 * after one, so writers capture the epoch at fetch start and the write is
 * dropped on a mismatch.
 */
const cache = new Map<string, ModelCatalogResponse>();

/** One dimension (the search text), so this stays small. */
const MAX_CACHE_ENTRIES = 8;

let epoch = 0;

export function modelCacheEpoch(): number {
  return epoch;
}

export function peekModelCatalogCache(key: string): ModelCatalogResponse | undefined {
  const hit = cache.get(key);
  if (hit !== undefined) {
    cache.delete(key);
    cache.set(key, hit);
  }
  return hit;
}

export function writeModelCatalogCache(
  key: string,
  value: ModelCatalogResponse,
  fetchedAtEpoch: number
): void {
  if (fetchedAtEpoch !== epoch) return;
  cache.delete(key);
  cache.set(key, value);
  while (cache.size > MAX_CACHE_ENTRIES) {
    const oldest = cache.keys().next();
    if (oldest.done) break;
    cache.delete(oldest.value);
  }
}

export function invalidateModelCatalogCache(): void {
  epoch += 1;
  cache.clear();
}

/** Stable key for a listing query, so a padded search cannot mint a second
 *  entry for the same answer. */
export function modelCatalogKey(params: { q?: string }): string {
  return JSON.stringify({ q: params.q?.trim() ?? "" });
}
