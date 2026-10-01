import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { useFlowContext } from './FlowProvider';
import {
  DATASET_CATALOG_REFRESH_EVENT,
  DatasetCatalogItem,
  installedComputedByProducer,
  useDatasetCatalog,
} from '../services/datasetCatalog';
import { buildSaveableLiveOutputs } from '../utils/saveOutputDataset';

export type DatasetPaletteContextValue = {
  /** datasetId targeted for reveal (open palette + scroll/highlight the row);
   * consumed after handling; cleared when the palette panel closes. */
  datasetRevealId: string | null;
  setDatasetRevealId: (id: string | null) => void;

  /** Producer node id → the installed computed dataset it generated. Derived from
   * the live catalog (one shared subscription) so producer chips stay in sync with
   * install/uninstall. See ``installedComputedByProducer``. */
  installedComputedByProducer: Map<string, DatasetCatalogItem>;

  /** This dataflow's datasets by id, for naming a node's DATASET pill (#442). */
  datasetsById?: Map<string, DatasetCatalogItem>;
};

const DatasetPaletteContext = createContext<DatasetPaletteContextValue | null>(null);

export function DatasetPaletteProvider({ children }: { children: React.ReactNode }) {
  const [datasetRevealId, setDatasetRevealId] = useState<string | null>(null);

  const { projectId, outputs, nodes, defaultSaveOutputDataset } = useFlowContext();

  // This dataflow's datasets only (`includeHub: false`), which is what the
  // producer pills need. Saveable live outputs surface freshly saved computed
  // datasets before the next project save.
  const liveOutputs = useMemo(
    () => buildSaveableLiveOutputs(outputs, nodes, defaultSaveOutputDataset),
    [outputs, nodes, defaultSaveOutputDataset],
  );

  const catalog = useDatasetCatalog({
    dataflowId: projectId,
    includeHub: false,
    sort: 'recent',
    liveOutputs,
    enabled: true,
  });

  // Auto-install / save fires this event; refetch so producer chips update live.
  useEffect(() => {
    const onRefresh = () => void catalog.reload();
    window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
  }, [catalog.reload]);

  const producerMap = useMemo(
    () => installedComputedByProducer(catalog.items),
    [catalog.items],
  );

  const datasetsById = useMemo(
    () => new Map(catalog.items.map((item) => [item.id, item] as const)),
    [catalog.items],
  );

  const value: DatasetPaletteContextValue = useMemo(
    () => ({
      datasetRevealId,
      setDatasetRevealId,
      installedComputedByProducer: producerMap,
      datasetsById,
    }),
    [datasetRevealId, producerMap, datasetsById],
  );

  return <DatasetPaletteContext.Provider value={value}>{children}</DatasetPaletteContext.Provider>;
}

export function useDatasetPalette(): DatasetPaletteContextValue {
  const ctx = useContext(DatasetPaletteContext);
  if (!ctx) {
    throw new Error('useDatasetPalette must be used within a DatasetPaletteProvider');
  }
  return ctx;
}
