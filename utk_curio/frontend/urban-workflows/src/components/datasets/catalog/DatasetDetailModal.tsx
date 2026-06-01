import React, { useEffect, useState } from "react";
import ModalShell from "../../ModalShell";
import { DatasetCatalogItem, datasetCatalogApi } from "../../../services/datasetCatalog";
import { DatasetDetailPanel } from "./DatasetDetailPanel";

export interface DatasetDetailModalProps {
  datasetId: string;
  dataflowId?: string | null;
  fallbackDataset?: DatasetCatalogItem | null;
  onClose: () => void;
}

export const DatasetDetailModal: React.FC<DatasetDetailModalProps> = ({
  datasetId,
  dataflowId = null,
  fallbackDataset = null,
  onClose,
}) => {
  const [dataset, setDataset] = useState<DatasetCatalogItem | null>(fallbackDataset);
  const [loading, setLoading] = useState(!fallbackDataset);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(!fallbackDataset);
    setError(null);
    if (fallbackDataset) setDataset(fallbackDataset);
    void datasetCatalogApi
      .getDataset(datasetId, { dataflowId })
      .then((item) => {
        if (!cancelled) setDataset(item);
      })
      .catch((err) => {
        if (!cancelled) {
          setError((err as Error)?.message || "Could not load dataset.");
          if (fallbackDataset) setDataset(fallbackDataset);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dataflowId, datasetId]);

  return (
    <ModalShell onClose={onClose} size="xlarge" layer="overlay">
      <DatasetDetailPanel
        dataset={dataset}
        loading={loading}
        error={error}
        variant="modal"
        dataflowId={dataflowId}
      />
    </ModalShell>
  );
};
