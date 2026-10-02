import { useCallback, useEffect, useRef, useState } from "react";

import { discoveryCatalogApi } from "./discoveryCatalogApi";
import {
  discoveryCacheEpoch,
  discoveryCatalogKey,
  peekDiscoveryCatalogCache,
  writeDiscoveryCatalogCache,
} from "./discoveryCatalogCache";
import type {
  DiscoveryAcquireBody,
  DiscoveryAcquireJob,
  DiscoveryAcquireStart,
  DiscoveryCatalogQuery,
  DiscoveryCatalogResponse,
  DiscoverySearchQuery,
  DiscoverySearchResponse,
} from "./discoveryCatalogTypes";
import { isTerminal } from "./discoveryCatalogTypes";

const EMPTY: DiscoveryCatalogResponse = {
  sources: [],
  facets: { provider: {}, auth: {} },
};

export interface UseDiscoveryCatalogResult {
  data: DiscoveryCatalogResponse;
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
export function useDiscoveryCatalog(params: DiscoveryCatalogQuery = {}): UseDiscoveryCatalogResult {
  const key = discoveryCatalogKey(params);
  const cached = peekDiscoveryCatalogCache(key);
  const [data, setData] = useState<DiscoveryCatalogResponse>(cached ?? EMPTY);
  const [loading, setLoading] = useState(cached === undefined);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  // Guards against a slow first response overwriting a fast later one when
  // the user types quickly enough to change the key mid-flight.
  const latest = useRef(0);

  useEffect(() => {
    const hit = peekDiscoveryCatalogCache(key);
    if (hit !== undefined) {
      setData(hit);
      setLoading(false);
    } else {
      setLoading(true);
    }
    const ticket = ++latest.current;
    const startedAt = discoveryCacheEpoch();
    let cancelled = false;
    discoveryCatalogApi
      .listCatalog(params)
      .then((res) => {
        if (cancelled || ticket !== latest.current) return;
        writeDiscoveryCatalogCache(key, res, startedAt);
        setData(res);
        setError(null);
      })
      .catch((err: Error) => {
        if (cancelled || ticket !== latest.current) return;
        setError(err.message || "Could not load the Discovery Catalog.");
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

const EMPTY_SEARCH: DiscoverySearchResponse = {
  resources: [],
  sources: [],
  nextCursor: null,
  totalHint: null,
  truncated: false,
};

export interface UseDiscoverySearchResult {
  data: DiscoverySearchResponse;
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
 * Search results are deliberately NOT cached - see `discoveryCatalogCache`.
 */
export function useDiscoverySearch(
  params: DiscoverySearchQuery & { sourceDir?: string }
): UseDiscoverySearchResult {
  const { sourceDir, q, format, provider, limit } = params;
  const [data, setData] = useState<DiscoverySearchResponse>(EMPTY_SEARCH);
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
    let timer: ReturnType<typeof setTimeout>;
    setLoading(true);

    const run = (polls: number) => {
      const request = sourceDir
        ? discoveryCatalogApi.searchSource(
            sourceDir,
            { q: query, format, limit },
            controller.signal
          )
        : discoveryCatalogApi.searchAll(
            { q: query, format, provider, limit },
            controller.signal
          );
      request
        .then((res) => {
          if (cancelled) return;
          setData(res);
          setError(null);
          setSearched(true);
          setLoading(false);
          // A storage source on its first scan answers "scanning": asked
          // again, quietly, until its rows are in, so they join the results
          // without a new query.
          const scanning = !sourceDir && res.sources.some((leg) => leg.status === "scanning");
          if (scanning && polls < MAX_SEARCH_SCAN_POLLS) {
            timer = setTimeout(() => run(polls + 1), SCAN_POLL_MS);
          }
        })
        .catch((err: Error) => {
          if (cancelled) return;
          setLoading(false);
          // An abort is the expected outcome of the next keystroke, not a
          // failure to report.
          if (err.name === "AbortError") return;
          setError(err.message || "That search could not be run.");
          setSearched(true);
        });
    };
    timer = setTimeout(() => run(0), SEARCH_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [sourceDir, q, format, provider, limit]);

  return { data, loading, error, searched };
}


// ── Storage listings ───────────────────────────────────────────────────────

/** How often a listing is asked again while its source is being scanned. */
const SCAN_POLL_MS = 1000;
/** How many times a federated search asks again for a source being scanned. */
const MAX_SEARCH_SCAN_POLLS = 30;
/** A storage search is answered from memory, so it only waits out typing. */
const STORAGE_DEBOUNCE_MS = 150;

export interface UseStorageListingResult extends UseDiscoverySearchResult {
  /** True while the source is being scanned, first or on Rescan. */
  scanning: boolean;
  /** Walk the source again, for files added since its last scan. */
  rescan: () => void;
}

/**
 * A storage source's rows: its declared resources as its last scan found them.
 *
 * A scan runs in the background on first use, so the first answer can be a
 * leg that says `scanning`; the listing then asks again until the scan ends.
 */
export function useStorageListing(sourceDir: string | undefined, q: string): UseStorageListingResult {
  const [data, setData] = useState<DiscoverySearchResponse>(EMPTY_SEARCH);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [rescanNonce, setRescanNonce] = useState(0);
  const lastRescan = useRef(0);

  useEffect(() => {
    if (!sourceDir) return;
    const controller = new AbortController();
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const rescan = rescanNonce !== lastRescan.current;
    lastRescan.current = rescanNonce;
    setLoading(true);

    const ask = (withRescan: boolean) => {
      discoveryCatalogApi
        .searchSource(sourceDir, { q: q.trim(), rescan: withRescan }, controller.signal)
        .then((res) => {
          if (cancelled) return;
          const still = res.sources.some((leg) => leg.status === "scanning");
          setScanning(still);
          setData(res);
          setError(null);
          setSearched(true);
          if (still) timer = setTimeout(() => ask(false), SCAN_POLL_MS);
          else setLoading(false);
        })
        .catch((err: Error) => {
          if (cancelled || err.name === "AbortError") return;
          setError(err.message || "That source could not be listed.");
          setSearched(true);
          setScanning(false);
          setLoading(false);
        });
    };
    timer = setTimeout(() => ask(rescan), rescan ? 0 : STORAGE_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [sourceDir, q, rescanNonce]);

  const rescan = useCallback(() => setRescanNonce((n) => n + 1), []);
  return { data, loading, error, searched, scanning, rescan };
}


// ── Acquisition ────────────────────────────────────────────────────────────

/** First poll delay, then backed off. Fast enough to feel responsive on a
 *  small file, slow enough not to hammer the backend on a large one. */
const POLL_START_MS = 1000;
const POLL_MAX_MS = 3000;

export interface UseDiscoveryAcquireResult {
  /** Jobs in flight or recently finished, keyed `<sourceId>:<resourceId>`. */
  jobs: Record<string, DiscoveryAcquireJob>;
  start: (dirName: string, resourceId: string, opts?: DiscoveryAcquireBody) => Promise<DiscoveryAcquireStart>;
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
 * or page that started it unmounts. The Discovery Catalog page and the Dataset
 * Finder's card share it, so the same resource shows one download in both.
 */
const acquisitions = {
  jobs: {} as Record<string, DiscoveryAcquireJob>,
  timers: {} as Record<string, ReturnType<typeof setTimeout>>,
  settled: {} as Record<string, Array<(job: DiscoveryAcquireJob) => void>>,
  listeners: new Set<() => void>(),
};

function publish(key: string, job: DiscoveryAcquireJob): void {
  acquisitions.jobs = { ...acquisitions.jobs, [key]: job };
  acquisitions.listeners.forEach((listener) => listener());
}

function settle(key: string, job: DiscoveryAcquireJob): void {
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
    discoveryCatalogApi
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
          ...(acquisitions.jobs[key] as DiscoveryAcquireJob),
          status: "failed",
          error: err.message || "Lost track of that download.",
        } as DiscoveryAcquireJob;
        publish(key, failed);
        settle(key, failed);
      });
  }, delay);
}

/**
 * Start a download, or learn at once that the account already holds it, and
 * call `onSettled` with the job's terminal state either way: `completed`
 * (with the dataset, also when it was already held), `failed`, `refused` or
 * `cancelled`. A request refused before any job exists settles as a `failed`
 * job on the row.
 */
export async function startDiscoveryAcquire(
  dirName: string,
  resourceId: string,
  opts: DiscoveryAcquireBody = {},
  onSettled?: (job: DiscoveryAcquireJob) => void,
): Promise<DiscoveryAcquireStart> {
  const key = acquireKey(dirName, resourceId);
  if (onSettled) (acquisitions.settled[key] ??= []).push(onSettled);
  // One job per row: its progress, its result and its Cancel are keyed by the
  // row, so a second start while one runs is the one already running.
  const current = acquisitions.jobs[key];
  if (current && !isTerminal(current.status)) return current;
  let started: DiscoveryAcquireStart;
  try {
    started = await discoveryCatalogApi.acquire(dirName, resourceId, opts);
  } catch (err) {
    // Refused before any job existed (too many downloads running, a
    // narrowing the source cannot satisfy): said on the row, as a job that
    // failed is.
    const refused: DiscoveryAcquireJob = {
      jobId: "",
      status: "failed",
      bytesRead: 0,
      totalBytes: null,
      stageMessage: "Failed",
      error: (err as Error)?.message || "That could not be started.",
      datasetId: null,
      dataset: null,
      alreadyPresent: false,
      unchanged: false,
      sourceId: dirName,
      resourceId,
    };
    publish(key, refused);
    settle(key, refused);
    return refused;
  }
  if (started.jobId) {
    publish(key, started as DiscoveryAcquireJob);
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
    } as DiscoveryAcquireJob;
    publish(key, held);
    settle(key, held);
  }
  return started;
}

/** Forget every download: for tests, which share the module between cases. */
export function resetDiscoveryAcquisitions(): void {
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
export function useDiscoveryAcquire(
  onCompleted?: (job: DiscoveryAcquireJob) => void
): UseDiscoveryAcquireResult {
  const [jobs, setJobs] = useState<Record<string, DiscoveryAcquireJob>>(acquisitions.jobs);
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
    (dirName: string, resourceId: string, opts: DiscoveryAcquireBody = {}) =>
      startDiscoveryAcquire(dirName, resourceId, opts, (job) => {
        if (job.status === "completed") done.current?.(job);
      }),
    []
  );

  const cancel = useCallback((dirName: string, resourceId: string) => {
    const job = acquisitions.jobs[acquireKey(dirName, resourceId)];
    if (!job?.jobId) return;
    void discoveryCatalogApi.cancelJob(job.jobId).catch(() => undefined);
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
