import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faTrashCan } from "@fortawesome/free-solid-svg-icons";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetProvenanceLabel,
} from "../../../services/datasetCatalog";
import {
  CatalogFormatBadge,
  CatalogItemRowHeader,
} from "../../catalog/CatalogKindVisuals";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import styles from "./InstalledDatasetsList.module.css";

export interface InstalledDatasetsListProps {
  datasets: DatasetCatalogItem[];
  busy?: boolean;
  publishAllowed?: boolean;
  publishingId?: string | null;
  refreshing?: boolean;
  sectionLabel?: string;
  onUninstall?: (dataset: DatasetCatalogItem) => void;
  onPublish?: (datasetId: string) => void;
  onUnpublish?: (dataset: DatasetCatalogItem) => void;
  onDragStart?: (dataset: DatasetCatalogItem, event: React.DragEvent<HTMLElement>) => void;
  onDragEnd?: () => void;
}

function InstalledDatasetRow({
  dataset,
  busy,
  publishAllowed,
  publishingId,
  onUninstall,
  onPublish,
  onUnpublish,
  onDragStart,
  onDragEnd,
}: {
  dataset: DatasetCatalogItem;
  busy: boolean;
  publishAllowed: boolean;
  publishingId: string | null;
  onUninstall?: (dataset: DatasetCatalogItem) => void;
  onPublish?: (datasetId: string) => void;
  onUnpublish?: (dataset: DatasetCatalogItem) => void;
  onDragStart?: (dataset: DatasetCatalogItem, event: React.DragEvent<HTMLElement>) => void;
  onDragEnd?: () => void;
}) {
  const isPublished = dataset.origin === "hub" || dataset.publishedToHub === true;
  const hasActions = onUninstall != null || onPublish != null || onUnpublish != null;

  return (
    <div
      className={styles.installedRow}
      draggable
      onDragStart={(event) => onDragStart?.(dataset, event)}
      onDragEnd={() => onDragEnd?.()}
    >
      <div className={styles.installedBody}>
        <div className={styles.installedHeader}>
          <CatalogItemRowHeader
            kind="dataset"
            badge={
              <CatalogFormatBadge
                label={DATASET_FORMAT_LABEL[dataset.format]}
                formatKey={dataset.format}
              />
            }
          />
          <span className={styles.installedName}>{dataset.title}</span>
        </div>
        <span className={styles.installedMeta}>
          {DATASET_FORMAT_LABEL[dataset.format]}
          {" · "}
          {datasetProvenanceLabel(dataset.origin)}
          {isPublished ? " · Published" : ""}
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
  refreshing = false,
  sectionLabel,
  onUninstall,
  onPublish,
  onUnpublish,
  onDragStart,
  onDragEnd,
}) => {
  if (datasets.length === 0) return null;

  const label = sectionLabel ?? `Your datasets · ${datasets.length} installed`;

  return (
    <>
      <p className={styles.sectionLabel}>{label}</p>
      <div
        className={styles.installedList}
        style={refreshing ? { opacity: 0.6, pointerEvents: "none", transition: "opacity 0.15s" } : { transition: "opacity 0.15s" }}
      >
        {datasets.map((dataset) => (
          <InstalledDatasetRow
            key={`${dataset.origin}:${dataset.id}`}
            dataset={dataset}
            busy={busy}
            publishAllowed={publishAllowed}
            publishingId={publishingId}
            onUninstall={onUninstall}
            onPublish={onPublish}
            onUnpublish={onUnpublish}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
          />
        ))}
      </div>
    </>
  );
};
