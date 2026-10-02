import { useCallback, useEffect, useRef, useState } from "react";

import { MODEL_CATALOG_REFRESH_EVENT, modelCatalogApi } from "./modelCatalogApi";
import {
  modelCacheEpoch,
  modelCatalogKey,
  peekModelCatalogCache,
  writeModelCatalogCache,
} from "./modelCatalogCache";
import type { ModelCatalogQuery, ModelCatalogResponse } from "./modelCatalogTypes";

const EMPTY: ModelCatalogResponse = { items: [] };

export interface UseModelCatalogOptions extends ModelCatalogQuery {
  /** When false, nothing is fetched (a closed drawer). The cache still
   *  hydrates the rows. */
  enabled?: boolean;
}

export interface UseModelCatalogResult {
  data: ModelCatalogResponse;
  loading: boolean;
  /** Present only when the fetch failed; the last good data stays visible. */
  error: string | null;
  reload: () => void;
}

/**
 * The model listing, cached and stale-while-revalidate, as
 * `useDiscoveryCatalog` serves the source roster.
 *
 * A cache hit renders immediately and still refetches, and a failed refetch
 * leaves the previous rows on screen with the error beside them. Every mounted
 * listing reloads on `notifyModelCatalogRefresh`, so a delete from the drawer
 * also leaves the palette and the page.
 */
export function useModelCatalog(options: UseModelCatalogOptions = {}): UseModelCatalogResult {
  const { enabled = true, ...params } = options;
  const key = modelCatalogKey(params);
  const cached = peekModelCatalogCache(key);
  const [data, setData] = useState<ModelCatalogResponse>(cached ?? EMPTY);
  const [loading, setLoading] = useState(enabled && cached === undefined);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  // Guards against a slow first response overwriting a fast later one when
  // the search text changes mid-flight.
  const latest = useRef(0);

  useEffect(() => {
    const hit = peekModelCatalogCache(key);
    if (hit !== undefined) {
      setData(hit);
      setLoading(false);
    }
    if (!enabled) return;
    if (hit === undefined) setLoading(true);
    const ticket = ++latest.current;
    const startedAt = modelCacheEpoch();
    let cancelled = false;
    modelCatalogApi
      .listCatalog(params)
      .then((res) => {
        if (cancelled || ticket !== latest.current) return;
        writeModelCatalogCache(key, res, startedAt);
        setData(res);
        setError(null);
      })
      .catch((err: Error) => {
        if (cancelled || ticket !== latest.current) return;
        setError(err.message || "Could not load the Model Catalog.");
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
  }, [key, nonce, enabled]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) return;
    window.addEventListener(MODEL_CATALOG_REFRESH_EVENT, reload);
    return () => window.removeEventListener(MODEL_CATALOG_REFRESH_EVENT, reload);
  }, [enabled, reload]);

  return { data, loading, error, reload };
}
