import { useCallback, useEffect, useRef, useState } from "react";

import { scenarioCatalogApi } from "./scenarioCatalogApi";
import type {
  ScenarioCatalogQuery,
  ScenarioCatalogResponse,
  ScenarioDetails,
} from "./scenarioCatalogTypes";

const EMPTY: ScenarioCatalogResponse = { items: [] };

export interface UseScenarioCatalogOptions extends ScenarioCatalogQuery {
  /** When false, nothing is fetched (a closed drawer). */
  enabled?: boolean;
}

export interface UseScenarioCatalogResult {
  data: ScenarioCatalogResponse;
  loading: boolean;
  /** Present only when the fetch failed; the last good rows stay visible. */
  error: string | null;
  reload: () => void;
}

/**
 * The scenario listing. Not cached across mounts, unlike the Model Catalog's:
 * it is read off the account's projects, which change with every save, so each
 * page visit and each drawer opening reads it afresh.
 */
export function useScenarioCatalog(options: UseScenarioCatalogOptions = {}): UseScenarioCatalogResult {
  const { enabled = true, q = "" } = options;
  const search = q.trim();
  const [data, setData] = useState<ScenarioCatalogResponse>(EMPTY);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  // A slow first response must not overwrite a fast later one when the search
  // text changes mid-flight.
  const latest = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    setLoading(true);
    const ticket = ++latest.current;
    let cancelled = false;
    scenarioCatalogApi
      .listCatalog({ q: search })
      .then((res) => {
        if (cancelled || ticket !== latest.current) return;
        setData(res);
        setError(null);
      })
      .catch((err: Error) => {
        if (cancelled || ticket !== latest.current) return;
        setError(err.message || "Could not load the Scenario Catalog.");
      })
      .finally(() => {
        if (cancelled || ticket !== latest.current) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [search, nonce, enabled]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload };
}

export interface UseScenarioDetailsResult {
  details: ScenarioDetails | null;
  loading: boolean;
  error: string | null;
}

/** One scenario's fixed context, levers and outcomes; nothing while *projectId*
 *  or *scenarioId* is missing. */
export function useScenarioDetails(
  projectId: string | null | undefined,
  scenarioId: string | null | undefined,
): UseScenarioDetailsResult {
  const [details, setDetails] = useState<ScenarioDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetails(null);
    setError(null);
    if (!projectId || !scenarioId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    let cancelled = false;
    scenarioCatalogApi
      .getScenario(projectId, scenarioId)
      .then((res) => {
        if (!cancelled) setDetails(res);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || "Could not load this scenario.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, scenarioId]);

  return { details, loading, error };
}
