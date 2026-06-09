import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { DatasetDetailPanel } from "../../components/datasets/catalog/DatasetDetailPanel";
import { useDatasetCatalog } from "../../services/datasetCatalog";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export const DataCatalogDetail: React.FC = () => {
  const navigate = useNavigate();
  const { datasetId } = useParams<{ datasetId: string }>();
  const catalog = useDatasetCatalog({ includeHub: true });
  const decodedDatasetId = datasetId ? decodeURIComponent(datasetId) : "";
  const dataset =
    catalog.items.find((item) => item.id === decodedDatasetId) || catalog.items[0] || null;

  return (
    <div className={styles.detailPage}>
      <DatasetDetailPanel
        dataset={dataset}
        loading={catalog.loading && catalog.items.length === 0}
        error={catalog.error}
        variant="page"
        onBack={() => navigate("/catalog/data")}
        onMutated={() => catalog.reload()}
      />
    </div>
  );
};

export default DataCatalogDetail;
