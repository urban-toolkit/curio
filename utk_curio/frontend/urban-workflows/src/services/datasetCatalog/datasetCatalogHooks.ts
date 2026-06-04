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

/** Stable cache key for a catalog fetch (tab filters are client-side only). */
function catalogFetchKey(query: StableCatalogQuery): string {
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

export function useDatasetCatalog(query: DatasetCatalogQuery = {}) {
  const [response, setResponse] = useState<DatasetCatalogResponse>(EMPTY_RESPONSE);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cacheByFetchKeyRef = useRef<Record<string, DatasetCatalogResponse>>({});
  const responseRef = useRef<DatasetCatalogResponse>(EMPTY_RESPONSE);
  const fetchGenRef = useRef(0);
  responseRef.current = response;

  const stableQuery = useMemo<StableCatalogQuery>(
    () => ({
      dataflowId: query.dataflowId || undefined,
      search: query.search || undefined,
      format: query.format || undefined,
      origin: query.origin || undefined,
      sort: query.sort || "recent",
      includeHub: query.includeHub ?? true,
      liveOutputs: query.liveOutputs,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      query.dataflowId, query.search, query.format, query.origin, query.sort, query.includeHub,
      JSON.stringify(query.liveOutputs),
    ],
  );

  const fetchKey = useMemo(() => catalogFetchKey(stableQuery), [stableQuery]);

  const reload = useCallback(async (options?: { bustCache?: boolean }) => {
    const gen = ++fetchGenRef.current;
    if (options?.bustCache) {
      delete cacheByFetchKeyRef.current[fetchKey];
    }
    const cached = cacheByFetchKeyRef.current[fetchKey];

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
      cacheByFetchKeyRef.current[fetchKey] = next;
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
  }, [fetchKey, stableQuery]);

  useEffect(() => {
    const cached = cacheByFetchKeyRef.current[fetchKey];
    if (cached) {
      setResponse(cached);
      setLoading(false);
      setRefreshing(false);
    }
    void reload();
  }, [fetchKey, reload]);

  const initialLoading = loading && response.items.length === 0;

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
