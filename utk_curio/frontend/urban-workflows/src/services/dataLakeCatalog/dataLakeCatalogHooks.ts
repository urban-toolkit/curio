import { useCallback, useEffect, useRef, useState } from "react";

import { dataLakeCatalogApi } from "./dataLakeCatalogApi";
import {
  lakeCacheEpoch,
  lakeCatalogKey,
  peekLakeCatalogCache,
  writeLakeCatalogCache,
} from "./dataLakeCatalogCache";
import type {
  LakeCatalogQuery,
  LakeCatalogResponse,
  LakeSearchQuery,
  LakeSearchResponse,
} from "./dataLakeCatalogTypes";

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


// ── Live search ────────────────────────────────────────────────────────────

/** Long enough that a typed word is one query, short enough to feel live. */
export const SEARCH_DEBOUNCE_MS = 400;

const EMPTY_SEARCH: LakeSearchResponse = {
  resources: [],
  sources: [],
  nextCursor: null,
  totalHint: null,
  truncated: false,
};

export interface UseLakeSearchResult {
  data: LakeSearchResponse;
  /** True while a query is settling or in flight. */
  loading: boolean;
  /** Only for a failure of the REQUEST. A portal that did not answer is not an
   *  error - it is a leg in `data.sources`. */
  error: string | null;
  /** True once a query has been issued, so an empty result can be told apart
   *  from not having searched yet. */
  searched: boolean;
}

/**
 * Search one portal, or all of them when `sourceDir` is omitted.
 *
 * Debounced and abortable. A fast typist must issue one fan-out, not one per
 * keystroke: a federated search is N real requests against N third parties,
 * and letting a five-letter word fire five of those is how a portal starts
 * rate-limiting Curio.
 *
 * Search results are deliberately NOT cached - see `dataLakeCatalogCache`.
 */
export function useLakeSearch(
  params: LakeSearchQuery & { sourceDir?: string }
): UseLakeSearchResult {
  const { sourceDir, q, format, provider, limit } = params;
  const [data, setData] = useState<LakeSearchResponse>(EMPTY_SEARCH);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    const query = (q || "").trim();
    // A federated search with no query would ask every portal for everything.
    // A scoped one is fine empty: a WFS source lists its whole catalogue.
    if (!query && !sourceDir) {
      setData(EMPTY_SEARCH);
      setLoading(false);
      setSearched(false);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);

    const timer = setTimeout(() => {
      const request = sourceDir
        ? dataLakeCatalogApi.searchSource(
            sourceDir,
            { q: query, format, limit },
            controller.signal
          )
        : dataLakeCatalogApi.searchAll(
            { q: query, format, provider, limit },
            controller.signal
          );
      request
        .then((res) => {
          if (cancelled) return;
          setData(res);
          setError(null);
          setSearched(true);
        })
        .catch((err: Error) => {
          // An abort is the expected outcome of the next keystroke, not a
          // failure to report.
          if (cancelled || err.name === "AbortError") return;
          setError(err.message || "That search could not be run.");
          setSearched(true);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [sourceDir, q, format, provider, limit]);

  return { data, loading, error, searched };
}
