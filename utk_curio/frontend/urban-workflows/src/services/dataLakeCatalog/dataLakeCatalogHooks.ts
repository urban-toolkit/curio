import { useCallback, useEffect, useRef, useState } from "react";

import { dataLakeCatalogApi } from "./dataLakeCatalogApi";
import {
  lakeCacheEpoch,
  lakeCatalogKey,
  peekLakeCatalogCache,
  writeLakeCatalogCache,
} from "./dataLakeCatalogCache";
import type {
  LakeAcquireJob,
  LakeAcquireStart,
  LakeCatalogQuery,
  LakeCatalogResponse,
  LakeSearchQuery,
  LakeSearchResponse,
} from "./dataLakeCatalogTypes";
import { isTerminal } from "./dataLakeCatalogTypes";

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


// ── Acquisition ────────────────────────────────────────────────────────────

/** First poll delay, then backed off. Fast enough to feel responsive on a
 *  small file, slow enough not to hammer the backend on a large one. */
const POLL_START_MS = 1000;
const POLL_MAX_MS = 3000;

export interface UseLakeAcquireResult {
  /** Jobs in flight or recently finished, keyed `<sourceId>:<resourceId>`. */
  jobs: Record<string, LakeAcquireJob>;
  start: (
    dirName: string,
    resourceId: string,
    opts?: { format?: string; title?: string; refresh?: boolean }
  ) => Promise<LakeAcquireStart>;
  cancel: (dirName: string, resourceId: string) => void;
  dismiss: (dirName: string, resourceId: string) => void;
}

export function acquireKey(sourceId: string, resourceId: string): string {
  return `${sourceId}:${resourceId}`;
}

/**
 * Every download started in this page session, keyed `<sourceId>:<resourceId>`.
 *
 * Held in the module rather than in a component, so a download keeps being
 * followed, and whoever started it still hears how it ended, after the card
 * or page that started it unmounts. The Data Lake page and the Dataset
 * Finder's card share it, so the same resource shows one download in both.
 */
const acquisitions = {
  jobs: {} as Record<string, LakeAcquireJob>,
  timers: {} as Record<string, ReturnType<typeof setTimeout>>,
  settled: {} as Record<string, Array<(job: LakeAcquireJob) => void>>,
  listeners: new Set<() => void>(),
};

function publish(key: string, job: LakeAcquireJob): void {
  acquisitions.jobs = { ...acquisitions.jobs, [key]: job };
  acquisitions.listeners.forEach((listener) => listener());
}

function settle(key: string, job: LakeAcquireJob): void {
  const waiting = acquisitions.settled[key] ?? [];
  delete acquisitions.settled[key];
  waiting.forEach((callback) => callback(job));
}

/**
 * Polling rather than a socket: a download is minutes at worst, the backend
 * already exposes the job, and a socket for this would be a second transport
 * to keep alive. It backs off, and stops the moment a job reaches a terminal
 * state - a poll loop that keeps running after the answer arrived is how a
 * backgrounded tab quietly generates traffic forever.
 */
function follow(key: string, jobId: string, delay: number): void {
  acquisitions.timers[key] = setTimeout(() => {
    dataLakeCatalogApi
      .getJob(jobId)
      .then((job) => {
        publish(key, job);
        if (isTerminal(job.status)) {
          delete acquisitions.timers[key];
          settle(key, job);
          return;
        }
        follow(key, jobId, Math.min(delay * 1.5, POLL_MAX_MS));
      })
      .catch((err: Error) => {
        // The job is gone, or the backend is. Either way, stop: retrying a
        // job we can no longer read is a loop with no exit.
        delete acquisitions.timers[key];
        const failed = {
          ...(acquisitions.jobs[key] as LakeAcquireJob),
          status: "failed",
          error: err.message || "Lost track of that download.",
        } as LakeAcquireJob;
        publish(key, failed);
        settle(key, failed);
      });
  }, delay);
}

/**
 * Start a download, or learn at once that the account already holds it, and
 * call `onSettled` with the job's terminal state either way: `completed`
 * (with the dataset, also when it was already held), `failed`, `refused` or
 * `cancelled`. A request that fails to start rejects instead.
 */
export async function startLakeAcquire(
  dirName: string,
  resourceId: string,
  opts: { format?: string; title?: string; refresh?: boolean } = {},
  onSettled?: (job: LakeAcquireJob) => void,
): Promise<LakeAcquireStart> {
  const key = acquireKey(dirName, resourceId);
  if (onSettled) (acquisitions.settled[key] ??= []).push(onSettled);
  let started: LakeAcquireStart;
  try {
    started = await dataLakeCatalogApi.acquire(dirName, resourceId, opts);
  } catch (err) {
    if (onSettled) {
      acquisitions.settled[key] = (acquisitions.settled[key] ?? []).filter((c) => c !== onSettled);
    }
    throw err;
  }
  if (started.jobId) {
    publish(key, started as LakeAcquireJob);
    if (!acquisitions.timers[key]) follow(key, started.jobId, POLL_START_MS);
  } else if (started.alreadyPresent) {
    const dataset = started.dataset ?? null;
    const held = {
      jobId: "",
      bytesRead: 0,
      totalBytes: null,
      stageMessage: "",
      error: null,
      unchanged: true,
      ...started,
      status: "completed",
      dataset,
      datasetId: (dataset?.id as string | undefined) ?? started.datasetId ?? null,
      alreadyPresent: true,
      sourceId: dirName,
      resourceId,
    } as LakeAcquireJob;
    publish(key, held);
    settle(key, held);
  }
  return started;
}

/** Forget every download: for tests, which share the module between cases. */
export function resetLakeAcquisitions(): void {
  Object.values(acquisitions.timers).forEach(clearTimeout);
  acquisitions.jobs = {};
  acquisitions.timers = {};
  acquisitions.settled = {};
  acquisitions.listeners.forEach((listener) => listener());
}

/**
 * Start downloads and follow them, from the shared store above. `onCompleted`
 * hears every download this component starts that completes, a resource the
 * account already held included.
 */
export function useLakeAcquire(
  onCompleted?: (job: LakeAcquireJob) => void
): UseLakeAcquireResult {
  const [jobs, setJobs] = useState<Record<string, LakeAcquireJob>>(acquisitions.jobs);
  const done = useRef(onCompleted);
  done.current = onCompleted;

  useEffect(() => {
    const listener = () => setJobs(acquisitions.jobs);
    acquisitions.listeners.add(listener);
    listener();
    return () => {
      acquisitions.listeners.delete(listener);
    };
  }, []);

  const start = useCallback(
    (dirName: string, resourceId: string, opts = {}) =>
      startLakeAcquire(dirName, resourceId, opts, (job) => {
        if (job.status === "completed") done.current?.(job);
      }),
    []
  );

  const cancel = useCallback((dirName: string, resourceId: string) => {
    const job = acquisitions.jobs[acquireKey(dirName, resourceId)];
    if (!job?.jobId) return;
    void dataLakeCatalogApi.cancelJob(job.jobId).catch(() => undefined);
  }, []);

  const dismiss = useCallback((dirName: string, resourceId: string) => {
    const key = acquireKey(dirName, resourceId);
    clearTimeout(acquisitions.timers[key]);
    delete acquisitions.timers[key];
    delete acquisitions.settled[key];
    const next = { ...acquisitions.jobs };
    delete next[key];
    acquisitions.jobs = next;
    acquisitions.listeners.forEach((listener) => listener());
  }, []);

  return { jobs, start, cancel, dismiss };
}
