import {
  invalidateLakeCatalogCache,
  lakeCacheEpoch,
  lakeCatalogKey,
  peekLakeCatalogCache,
  writeLakeCatalogCache,
} from '../../services/dataLakeCatalog/dataLakeCatalogCache';
import type { LakeCatalogResponse } from '../../services/dataLakeCatalog';

const body = (n: number): LakeCatalogResponse => ({
  sources: [{ sourceId: `lake.s.${n}` } as never],
  facets: { provider: {}, auth: {} },
});

beforeEach(() => invalidateLakeCatalogCache());

describe('lakeCatalogKey', () => {
  test('two equivalent queries mint one entry', () => {
    expect(lakeCatalogKey({ q: ' chicago ' })).toBe(lakeCatalogKey({ q: 'chicago' }));
    expect(lakeCatalogKey({})).toBe(lakeCatalogKey({ q: '', provider: '', auth: '' }));
  });

  test('a different filter is a different entry', () => {
    expect(lakeCatalogKey({ provider: 'ckan' })).not.toBe(lakeCatalogKey({ provider: 'wfs' }));
  });
});

describe('the roster cache', () => {
  test('round-trips a write', () => {
    const key = lakeCatalogKey({});
    writeLakeCatalogCache(key, body(1), lakeCacheEpoch());
    expect(peekLakeCatalogCache(key)).toEqual(body(1));
  });

  test('invalidation clears everything, not just one key', () => {
    writeLakeCatalogCache('a', body(1), lakeCacheEpoch());
    writeLakeCatalogCache('b', body(2), lakeCacheEpoch());
    invalidateLakeCatalogCache();
    expect(peekLakeCatalogCache('a')).toBeUndefined();
    expect(peekLakeCatalogCache('b')).toBeUndefined();
  });

  test('a write from before an invalidation is dropped', () => {
    // The race this exists for: a fetch starts, the roster changes, the fetch
    // resolves with pre-change data. Without the epoch it would repopulate the
    // cache with exactly the rows the invalidation was meant to discard.
    const stale = lakeCacheEpoch();
    invalidateLakeCatalogCache();
    writeLakeCatalogCache('a', body(1), stale);
    expect(peekLakeCatalogCache('a')).toBeUndefined();
  });

  test('it evicts least-recently-used rather than growing forever', () => {
    for (let i = 0; i < 12; i += 1) {
      writeLakeCatalogCache(`k${i}`, body(i), lakeCacheEpoch());
    }
    expect(peekLakeCatalogCache('k0')).toBeUndefined();
    expect(peekLakeCatalogCache('k11')).toBeDefined();
  });

  test('a peek refreshes recency, so a hot key survives eviction', () => {
    writeLakeCatalogCache('hot', body(0), lakeCacheEpoch());
    for (let i = 0; i < 7; i += 1) {
      writeLakeCatalogCache(`k${i}`, body(i), lakeCacheEpoch());
      peekLakeCatalogCache('hot');
    }
    expect(peekLakeCatalogCache('hot')).toBeDefined();
  });
});

describe('what is deliberately NOT cached', () => {
  test('the module caches rosters only, and exposes no search cache', () => {
    // A portal can publish, withdraw or rename a dataset between two searches,
    // so a cached search row leads to a download that 404s against something
    // the user was just shown. If a `writeLakeSearchCache` ever appears here,
    // that decision is being reversed and should be argued for, not slipped in.
    const api = require('../../services/dataLakeCatalog/dataLakeCatalogCache');
    expect(Object.keys(api).filter((k) => /search/i.test(k))).toEqual([]);
  });
});
