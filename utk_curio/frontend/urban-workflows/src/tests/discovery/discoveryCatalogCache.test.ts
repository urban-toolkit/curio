import {
  invalidateDiscoveryCatalogCache,
  discoveryCacheEpoch,
  discoveryCatalogKey,
  peekDiscoveryCatalogCache,
  writeDiscoveryCatalogCache,
} from '../../services/discoveryCatalog/discoveryCatalogCache';
import type { DiscoveryCatalogResponse } from '../../services/discoveryCatalog';

const body = (n: number): DiscoveryCatalogResponse => ({
  sources: [{ sourceId: `source.s.${n}` } as never],
  facets: { provider: {}, auth: {} },
});

beforeEach(() => invalidateDiscoveryCatalogCache());

describe('discoveryCatalogKey', () => {
  test('two equivalent queries mint one entry', () => {
    expect(discoveryCatalogKey({ q: ' chicago ' })).toBe(discoveryCatalogKey({ q: 'chicago' }));
    expect(discoveryCatalogKey({})).toBe(discoveryCatalogKey({ q: '', provider: '', auth: '' }));
  });

  test('a different filter is a different entry', () => {
    expect(discoveryCatalogKey({ provider: 'ckan' })).not.toBe(discoveryCatalogKey({ provider: 'wfs' }));
  });
});

describe('the roster cache', () => {
  test('round-trips a write', () => {
    const key = discoveryCatalogKey({});
    writeDiscoveryCatalogCache(key, body(1), discoveryCacheEpoch());
    expect(peekDiscoveryCatalogCache(key)).toEqual(body(1));
  });

  test('invalidation clears everything, not just one key', () => {
    writeDiscoveryCatalogCache('a', body(1), discoveryCacheEpoch());
    writeDiscoveryCatalogCache('b', body(2), discoveryCacheEpoch());
    invalidateDiscoveryCatalogCache();
    expect(peekDiscoveryCatalogCache('a')).toBeUndefined();
    expect(peekDiscoveryCatalogCache('b')).toBeUndefined();
  });

  test('a write from before an invalidation is dropped', () => {
    // The race this exists for: a fetch starts, the roster changes, the fetch
    // resolves with pre-change data. Without the epoch it would repopulate the
    // cache with exactly the rows the invalidation was meant to discard.
    const stale = discoveryCacheEpoch();
    invalidateDiscoveryCatalogCache();
    writeDiscoveryCatalogCache('a', body(1), stale);
    expect(peekDiscoveryCatalogCache('a')).toBeUndefined();
  });

  test('it evicts least-recently-used rather than growing forever', () => {
    for (let i = 0; i < 12; i += 1) {
      writeDiscoveryCatalogCache(`k${i}`, body(i), discoveryCacheEpoch());
    }
    expect(peekDiscoveryCatalogCache('k0')).toBeUndefined();
    expect(peekDiscoveryCatalogCache('k11')).toBeDefined();
  });

  test('a peek refreshes recency, so a hot key survives eviction', () => {
    writeDiscoveryCatalogCache('hot', body(0), discoveryCacheEpoch());
    for (let i = 0; i < 7; i += 1) {
      writeDiscoveryCatalogCache(`k${i}`, body(i), discoveryCacheEpoch());
      peekDiscoveryCatalogCache('hot');
    }
    expect(peekDiscoveryCatalogCache('hot')).toBeDefined();
  });
});

describe('what is deliberately NOT cached', () => {
  test('the module caches rosters only, and exposes no search cache', () => {
    // A portal can publish, withdraw or rename a dataset between two searches,
    // so a cached search row leads to a download that 404s against something
    // the user was just shown. If a `writeDiscoverySearchCache` ever appears here,
    // that decision is being reversed and should be argued for, not slipped in.
    const api = require('../../services/discoveryCatalog/discoveryCatalogCache');
    expect(Object.keys(api).filter((k) => /search/i.test(k))).toEqual([]);
  });
});
