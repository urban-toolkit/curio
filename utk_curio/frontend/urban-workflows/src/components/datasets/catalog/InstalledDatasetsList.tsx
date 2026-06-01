import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faTrashCan } from "@fortawesome/free-solid-svg-icons";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
} from "../../../services/datasetCatalog";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import styles from "./InstalledDatasetsList.module.css";

export interface InstalledDatasetsListProps {
  datasets: DatasetCatalogItem[];
  busy?: boolean;
  publishAllowed?: boolean;
  publishingId?: string | null;
  onUninstall?: (dataset: DatasetCatalogItem) => void;
  onPublish?: (datasetId: string) => void;
  onDragStart?: (dataset: DatasetCatalogItem, event: React.DragEvent<HTMLElement>) => void;
}

function InstalledDatasetRow({
  dataset,
  busy,
  publishAllowed,
  publishingId,
  onUninstall,
  onPublish,
  onDragStart,
}: {
  dataset: DatasetCatalogItem;
  busy: boolean;
  publishAllowed: boolean;
  publishingId: string | null;
  onUninstall?: (dataset: DatasetCatalogItem) => void;
  onPublish?: (datasetId: string) => void;
  onDragStart?: (dataset: DatasetCatalogItem, event: React.DragEvent<HTMLElement>) => void;
}) {
  const isPublished = dataset.origin === "hub";
  const hasActions = onUninstall != null || onPublish != null;

  return (
    <div
      className={styles.installedRow}
      draggable
      onDragStart={(event) => onDragStart?.(dataset, event)}
    >
      <span className={styles.installedDot} aria-hidden />
      <div className={styles.installedBody}>
        <span className={styles.installedName}>{dataset.title}</span>
        <span className={styles.installedMeta}>
          {DATASET_FORMAT_LABEL[dataset.format]} · {dataset.origin === "hub" ? "Data Hub" : "In dataflow"}
        </span>
      </div>
      {hasActions ? (
        <div className={styles.installedActions}>
          {onPublish != null ? (
            <CatalogPublishPill
              variant="dock"
              dirName={dataset.id}
              published={isPublished}
              allowPublish={publishAllowed}
              busy={publishingId === dataset.id}
              onPublish={onPublish}
            />
          ) : null}
          {onUninstall != null ? (
            <button
              type="button"
              className={styles.rowActionBtn}
              title="Remove dataset"
              aria-label={`Remove ${dataset.title}`}
              disabled={busy}
              onClick={() => onUninstall(dataset)}
            >
              <FontAwesomeIcon icon={faTrashCan} aria-hidden />
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export const InstalledDatasetsList: React.FC<InstalledDatasetsListProps> = ({
  datasets,
  busy = false,
  publishAllowed = true,
  publishingId = null,
  onUninstall,
  onPublish,
  onDragStart,
}) => {
  if (datasets.length === 0) return null;

  return (
    <>
      <p className={styles.sectionLabel}>Your datasets · {datasets.length} installed</p>
      <div className={styles.installedList}>
        {datasets.map((dataset) => (
          <InstalledDatasetRow
            key={`${dataset.origin}:${dataset.id}`}
            dataset={dataset}
            busy={busy}
            publishAllowed={publishAllowed}
            publishingId={publishingId}
            onUninstall={onUninstall}
            onPublish={onPublish}
            onDragStart={onDragStart}
          />
        ))}
      </div>
    </>
  );
};
