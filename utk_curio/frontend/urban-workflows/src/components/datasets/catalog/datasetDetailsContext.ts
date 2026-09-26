import { createContext, useContext } from "react";

import type { DatasetCatalogItem } from "../../../services/datasetCatalog";

export interface OpenDatasetDetailsOptions {
  /** Shown while the dataset's own record loads, so the modal never opens blank. */
  fallbackDataset?: DatasetCatalogItem | null;
  /** Known to the caller already; otherwise the modal reads it. */
  inAllProjects?: boolean;
  /** Called after the modal closes. */
  onClose?: () => void;
}

export interface DatasetDetailsRequest extends OpenDatasetDetailsOptions {
  datasetId: string;
}

export interface DatasetDetailsContextValue {
  openDatasetDetails: (datasetId: string, options?: OpenDatasetDetailsOptions) => void;
}

/**
 * How anything opens a dataset's details: `useDatasetDetails().openDatasetDetails(id)`.
 *
 * Kept apart from `DatasetDetailsProvider`, which renders the modal and so pulls
 * in everything the modal renders. A caller needs only this.
 */
export const DatasetDetailsContext = createContext<DatasetDetailsContextValue | null>(null);

const NO_PROVIDER: DatasetDetailsContextValue = {
  openDatasetDetails: () => {
    if (process.env.NODE_ENV !== "production") {
      console.warn("[curio] openDatasetDetails called outside a DatasetDetailsProvider");
    }
  },
};

export function useDatasetDetails(): DatasetDetailsContextValue {
  return useContext(DatasetDetailsContext) ?? NO_PROVIDER;
}

/** The "View details" a toast about a dataset offers: the same modal a card
 *  or a row opens. Pass it as `showToast`'s third argument. */
export function viewDatasetDetailsToast(
  open: DatasetDetailsContextValue["openDatasetDetails"],
  datasetId: string,
  options?: OpenDatasetDetailsOptions,
): { action: { label: string; onClick: () => void } } {
  return { action: { label: "View details", onClick: () => open(datasetId, options) } };
}
