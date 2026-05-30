import { useCallback, useEffect, useMemo, useState } from "react";
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

export function useDatasetCatalog(query: DatasetCatalogQuery = {}) {
  const [response, setResponse] = useState<DatasetCatalogResponse>(EMPTY_RESPONSE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stableQuery = useMemo(
    () => ({
      dataflowId: query.dataflowId || undefined,
      search: query.search || undefined,
      format: query.format || undefined,
      origin: query.origin || undefined,
      sort: query.sort || "recent",
      includeHub: query.includeHub,
    }),
    [query.dataflowId, query.search, query.format, query.origin, query.sort, query.includeHub],
  );

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await datasetCatalogApi.listCatalog(stableQuery);
      setResponse(next);
    } catch (err) {
      const message = (err as Error)?.message || "Could not load datasets.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [stableQuery]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const install = useCallback(
    async (dataset: DatasetCatalogItem) => {
      if (!stableQuery.dataflowId) {
        throw new Error("Save the dataflow before installing datasets.");
      }
      const item = await datasetCatalogApi.installToDataflow(stableQuery.dataflowId, dataset.id);
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
    loading,
    error,
    reload,
    install,
    uninstall,
    importDataset,
  };
}
