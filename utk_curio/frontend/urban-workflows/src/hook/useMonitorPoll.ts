import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Poll one endpoint on an interval, with a pause and a last-updated stamp.
 *
 * Four behaviours here are deliberate, and each one is a bug the obvious
 * implementation has:
 *
 * - **`loading` is true only while there is no data yet.** The convention
 *   `DataCatalogDetail` already follows. A poll must never blank a page that
 *   is already showing numbers.
 * - **A failed tick keeps the previous data.** The page shows a stale banner
 *   over live numbers rather than throwing away what it has, because the most
 *   likely reason a monitor request fails is the thing being monitored.
 * - **The next tick is scheduled in the previous one's `finally`,** not on a
 *   `setInterval`. An interval against a backend slower than the interval
 *   stacks requests until something falls over.
 * - **A hidden tab does not poll.** These are public endpoints and a forgotten
 *   background tab would otherwise hit them forever.
 */
export interface MonitorPoll<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  lastUpdatedAt: Date | null;
  reload: () => void;
}

export function useMonitorPoll<T>(
  fetcher: (signal?: AbortSignal) => Promise<T>,
  intervalMs: number,
  paused: boolean
): MonitorPoll<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const pausedRef = useRef(paused);
  const fetcherRef = useRef(fetcher);

  // Kept in refs so the polling loop below never has to be torn down and
  // rebuilt when the caller re-renders with a new closure.
  pausedRef.current = paused;
  fetcherRef.current = fetcher;

  const tick = useCallback(async () => {
    if (!mounted.current) return;

    controller.current?.abort();
    const ac = new AbortController();
    controller.current = ac;

    try {
      const next = await fetcherRef.current(ac.signal);
      if (!mounted.current || ac.signal.aborted) return;
      setData(next);
      setError(null);
      setLastUpdatedAt(new Date());
    } catch (err) {
      if (!mounted.current || ac.signal.aborted) return;
      // Previous data is deliberately left in place.
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (mounted.current && !pausedRef.current) {
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => void tick(), intervalMs);
      }
    }
  }, [intervalMs]);

  const reload = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    void tick();
  }, [tick]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (timer.current) clearTimeout(timer.current);
      controller.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (paused) {
      if (timer.current) clearTimeout(timer.current);
      return;
    }
    void tick();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [paused, tick]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "visible" && !pausedRef.current) {
        reload();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [reload]);

  return { data, error, loading: data === null, lastUpdatedAt, reload };
}

export default useMonitorPoll;
