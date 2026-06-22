import React, {
  createContext,
  useContext,
  useMemo,
  useState,
} from 'react';

export type DatasetPaletteContextValue = {
  /** datasetId targeted for reveal (open palette + scroll/highlight the row);
   * consumed after handling; cleared when the palette panel closes. */
  datasetRevealId: string | null;
  setDatasetRevealId: (id: string | null) => void;
};

const DatasetPaletteContext = createContext<DatasetPaletteContextValue | null>(null);

export function DatasetPaletteProvider({ children }: { children: React.ReactNode }) {
  const [datasetRevealId, setDatasetRevealId] = useState<string | null>(null);

  const value: DatasetPaletteContextValue = useMemo(
    () => ({ datasetRevealId, setDatasetRevealId }),
    [datasetRevealId],
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
