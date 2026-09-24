import { useCallback, useEffect, useRef, useState } from "react";

import { dataLakeCatalogApi } from "./dataLakeCatalogApi";
import {
  lakeCacheEpoch,
  lakeCatalogKey,
  peekLakeCatalogCache,
  writeLakeCatalogCache,
} from "./dataLakeCatalogCache";
import type { LakeCatalogQuery, LakeCatalogResponse } from "./dataLakeCatalogTypes";

const EMPTY: LakeCatalogResponse = {
  sources: [],
  facets: { provider: {}, auth: {} },
};

export interface UseLakeCatalogResult {
  data: LakeCatalogResponse;
  loading: boolean;
  /** Present only when the fetch failed; the last good data stays visible. */
  error: string | null;
  reload: () => void;
}

/**
 * The source roster, cached and stale-while-revalidate.
 *
 * A cache hit renders immediately and still refetches, so switching to this
 * tab never shows a spinner over content we already have. A failed refetch
 * leaves the previous rows on screen with an error beside them rather than
 * replacing a working page with an error box.
 */
export function useLakeCatalog(params: LakeCatalogQuery = {}): UseLakeCatalogResult {
  const key = lakeCatalogKey(params);
  const cached = peekLakeCatalogCache(key);
  const [data, setData] = useState<LakeCatalogResponse>(cached ?? EMPTY);
  const [loading, setLoading] = useState(cached === undefined);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  // Guards against a slow first response overwriting a fast later one when
  // the user types quickly enough to change the key mid-flight.
  const latest = useRef(0);

  useEffect(() => {
    const hit = peekLakeCatalogCache(key);
    if (hit !== undefined) {
      setData(hit);
      setLoading(false);
    } else {
      setLoading(true);
    }
    const ticket = ++latest.current;
    const startedAt = lakeCacheEpoch();
    let cancelled = false;
    dataLakeCatalogApi
      .listCatalog(params)
      .then((res) => {
        if (cancelled || ticket !== latest.current) return;
        writeLakeCatalogCache(key, res, startedAt);
        setData(res);
        setError(null);
      })
      .catch((err: Error) => {
        if (cancelled || ticket !== latest.current) return;
        setError(err.message || "Could not load the data lake catalog.");
      })
      .finally(() => {
        if (cancelled || ticket !== latest.current) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // `key` is the serialised form of every field of `params`, so it is the
    // whole dependency; listing `params` itself would refetch on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload };
}
