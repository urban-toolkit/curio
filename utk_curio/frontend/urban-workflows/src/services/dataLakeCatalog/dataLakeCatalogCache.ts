import type { LakeCatalogResponse } from "./dataLakeCatalogTypes";

/**
 * Cache for the source ROSTER only.
 *
 * The roster is disk-backed, small, and changes only when an operator edits
 * the catalog, so caching it is free and makes tab switches instant.
 *
 * **Live search results are deliberately never cached.** They are remote state
 * we do not own: a portal can publish, withdraw or rename a dataset between
 * two searches, and serving a stale row leads to a download that 404s against
 * a resource the user was just shown. A slightly slower search is a better
 * failure than a confidently wrong one.
 *
 * Epoch-based invalidation, matching `datasetCatalogCache`: a fetch that
 * STARTED before an invalidation must not repopulate the cache when it
 * resolves after one, so writers capture the epoch at fetch start and the
 * write is dropped on a mismatch.
 */
const cache = new Map<string, LakeCatalogResponse>();

/** The roster has one dimension (the filter query), so this stays small. */
const MAX_CACHE_ENTRIES = 8;

let epoch = 0;

export function lakeCacheEpoch(): number {
  return epoch;
}

export function peekLakeCatalogCache(key: string): LakeCatalogResponse | undefined {
  const hit = cache.get(key);
  if (hit !== undefined) {
    cache.delete(key);
    cache.set(key, hit);
  }
  return hit;
}

export function writeLakeCatalogCache(
  key: string,
  value: LakeCatalogResponse,
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

export function invalidateLakeCatalogCache(): void {
  epoch += 1;
  cache.clear();
}

/** Stable key for a roster query. Field order is fixed, so two equivalent
 *  queries cannot mint two entries. */
export function lakeCatalogKey(params: {
  q?: string;
  provider?: string;
  auth?: string;
}): string {
  return JSON.stringify({
    q: params.q?.trim() ?? "",
    provider: params.provider ?? "",
    auth: params.auth ?? "",
  });
}
