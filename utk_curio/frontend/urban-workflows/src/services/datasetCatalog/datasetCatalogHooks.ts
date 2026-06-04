import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { datasetCatalogApi } from "./datasetCatalogApi";
import {
  DatasetCatalogItem,
  DatasetCatalogQuery,
  DatasetCatalogResponse,
} from "./datasetCatalogTypes";

const EMPTY_RESPONSE: DatasetCatalogResponse = {
  items: [],
  facets: {
    origin: { source_node: 0, computed: 0, imported: 0, hub: 0 },
    format: { csv: 0, geojson: 0, json: 0, parquet: 0, geotiff: 0, shp: 0 },
  },
};

type StableCatalogQuery = {
  dataflowId?: string;
  search?: string;
  format?: string;
  origin?: string;
  sort?: string;
  includeHub?: boolean;
  liveOutputs?: DatasetCatalogQuery["liveOutputs"];
};

/** Shared across hook instances (drawer, palette, prefetch). */
const catalogResponseCache: Record<string, DatasetCatalogResponse> = {};

/** Stable cache key for a catalog fetch (tab filters are client-side only). */
export function catalogFetchKey(query: StableCatalogQuery): string {
  return JSON.stringify({
    dataflowId: query.dataflowId ?? "",
    includeHub: query.includeHub ?? true,
    search: query.search ?? "",
    sort: query.sort ?? "recent",
    origin: query.origin ?? "",
    format: query.format ?? "",
    liveOutputs: query.liveOutputs ?? null,
  });
}

export function toStableCatalogQuery(query: DatasetCatalogQuery = {}): StableCatalogQuery {
  return {
    dataflowId: query.dataflowId || undefined,
    search: query.search || undefined,
    format: query.format || undefined,
    origin: query.origin || undefined,
    sort: query.sort || "recent",
    includeHub: query.includeHub ?? true,
    liveOutputs: query.liveOutputs,
  };
}

export function peekCatalogCache(fetchKey: string): DatasetCatalogResponse | undefined {
  return catalogResponseCache[fetchKey];
}

/** Warm the shared catalog cache without subscribing (e.g. before opening the drawer). */
export function prefetchDatasetCatalog(query: DatasetCatalogQuery = {}): void {
  const stableQuery = toStableCatalogQuery(query);
  const fetchKey = catalogFetchKey(stableQuery);
  if (catalogResponseCache[fetchKey]) return;

  void datasetCatalogApi.listCatalog(stableQuery).then((next) => {
    catalogResponseCache[fetchKey] = next;
  }).catch(() => {
    /* ignore — the drawer hook will surface errors on open */
  });
}

export type UseDatasetCatalogOptions = DatasetCatalogQuery & {
  /** When false, skip network fetch until enabled (drawer closed). Cache still hydrates UI. */
  enabled?: boolean;
};

export function useDatasetCatalog(query: UseDatasetCatalogOptions = {}) {
  const { enabled = true, ...queryRest } = query;
  const stableQuery = useMemo<StableCatalogQuery>(
    () => toStableCatalogQuery(queryRest),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      queryRest.dataflowId,
      queryRest.search,
      queryRest.format,
      queryRest.origin,
      queryRest.sort,
      queryRest.includeHub,
      JSON.stringify(queryRest.liveOutputs),
    ],
  );

  const fetchKey = useMemo(() => catalogFetchKey(stableQuery), [stableQuery]);

  const [response, setResponse] = useState<DatasetCatalogResponse>(
    () => peekCatalogCache(fetchKey) ?? EMPTY_RESPONSE,
  );
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const responseRef = useRef<DatasetCatalogResponse>(EMPTY_RESPONSE);
  const fetchGenRef = useRef(0);
  responseRef.current = response;

  const reload = useCallback(async (options?: { bustCache?: boolean }) => {
    if (!enabled) return;
    const gen = ++fetchGenRef.current;
    if (options?.bustCache) {
      delete catalogResponseCache[fetchKey];
    }
    const cached = catalogResponseCache[fetchKey];

    if (cached) {
      setResponse(cached);
      setRefreshing(true);
      setLoading(false);
    } else if (responseRef.current.items.length > 0) {
      setRefreshing(true);
      setLoading(false);
    } else {
      setLoading(true);
      setRefreshing(false);
    }
    setError(null);

    try {
      const next = await datasetCatalogApi.listCatalog(stableQuery);
      if (gen !== fetchGenRef.current) {
        return;
      }
      catalogResponseCache[fetchKey] = next;
      setResponse(next);
      setError(null);
    } catch (err) {
      if (gen !== fetchGenRef.current) {
        return;
      }
      const message = (err as Error)?.message || "Could not load datasets.";
      setError(message);
    } finally {
      if (gen === fetchGenRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [enabled, fetchKey, stableQuery]);

  // Hydrate from shared cache when the fetch key changes (e.g. project load).
  useEffect(() => {
    const cached = catalogResponseCache[fetchKey];
    if (cached) {
      setResponse(cached);
      setLoading(false);
      setRefreshing(false);
    }
  }, [fetchKey]);

  useEffect(() => {
    if (!enabled) return;
    void reload();
  }, [enabled, fetchKey, reload]);

  const initialLoading = enabled && loading && response.items.length === 0;

  const install = useCallback(
    async (dataset: DatasetCatalogItem) => {
      if (!stableQuery.dataflowId) {
        throw new Error("Save the dataflow before installing datasets.");
      }
      const item = await datasetCatalogApi.installToDataflow(stableQuery.dataflowId, dataset.id, dataset);
      await reload();
      return item;
    },
    [reload, stableQuery.dataflowId],
  );

  const uninstall = useCallback(
    async (dataset: DatasetCatalogItem) => {
      if (!stableQuery.dataflowId) return;
      await datasetCatalogApi.uninstallFromDataflow(stableQuery.dataflowId, dataset.id);
      await reload();
    },
    [reload, stableQuery.dataflowId],
  );

  const importDataset = useCallback(
    async (file: File) => {
      const item = await datasetCatalogApi.importDataset(file, { dataflowId: stableQuery.dataflowId });
      await reload();
      return item;
    },
    [reload, stableQuery.dataflowId],
  );

  return {
    items: response.items,
    facets: response.facets,
    loading: initialLoading,
    refreshing,
    error,
    reload,
    install,
    uninstall,
    importDataset,
  };
}
