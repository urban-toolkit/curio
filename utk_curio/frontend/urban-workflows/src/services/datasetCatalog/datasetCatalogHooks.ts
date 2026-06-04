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

function catalogScopeKey(query: {
  dataflowId?: string;
  includeHub?: boolean;
}): string {
  return `${query.dataflowId ?? ""}\u0000${String(query.includeHub)}`;
}

export function useDatasetCatalog(query: DatasetCatalogQuery = {}) {
  const [response, setResponse] = useState<DatasetCatalogResponse>(EMPTY_RESPONSE);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Last successful payload; kept visible while a background refetch runs. */
  const committedRef = useRef<DatasetCatalogResponse>(EMPTY_RESPONSE);
  const prevScopeKeyRef = useRef<string | null>(null);
  const fetchGenRef = useRef(0);

  const stableQuery = useMemo(
    () => ({
      dataflowId: query.dataflowId || undefined,
      search: query.search || undefined,
      format: query.format || undefined,
      origin: query.origin || undefined,
      sort: query.sort || "recent",
      includeHub: query.includeHub,
      liveOutputs: query.liveOutputs,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      query.dataflowId, query.search, query.format, query.origin, query.sort, query.includeHub,
      // Serialize liveOutputs so the memo updates when the outputs array changes
      // (comparing array references would always differ on re-render).
      // eslint-disable-next-line react-hooks/exhaustive-deps
      JSON.stringify(query.liveOutputs),
    ],
  );

  const scopeKey = useMemo(
    () => catalogScopeKey({ dataflowId: stableQuery.dataflowId, includeHub: stableQuery.includeHub }),
    [stableQuery.dataflowId, stableQuery.includeHub],
  );

  const reload = useCallback(async () => {
    const gen = ++fetchGenRef.current;

    if (prevScopeKeyRef.current !== scopeKey) {
      if (prevScopeKeyRef.current != null) {
        committedRef.current = EMPTY_RESPONSE;
        setResponse(EMPTY_RESPONSE);
      }
      prevScopeKeyRef.current = scopeKey;
    }

    const keepPreviousVisible = committedRef.current.items.length > 0;
    if (keepPreviousVisible) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const next = await datasetCatalogApi.listCatalog(stableQuery);
      if (gen !== fetchGenRef.current) {
        return;
      }
      committedRef.current = next;
      setResponse(next);
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
  }, [scopeKey, stableQuery]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const display = refreshing ? committedRef.current : response;

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
    items: display.items,
    facets: display.facets,
    loading,
    refreshing,
    error,
    reload,
    install,
    uninstall,
    importDataset,
  };
}
