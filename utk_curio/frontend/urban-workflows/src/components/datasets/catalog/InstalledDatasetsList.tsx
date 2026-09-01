import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faTrashCan, faSpinner } from "@fortawesome/free-solid-svg-icons";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  PendingInstall,
  datasetDisplayTitle,
  datasetProvenanceLabel,
  isDatasetPublishedToCatalog,
} from "../../../services/datasetCatalog";
import {
  CatalogFormatBadge,
  CatalogItemRowHeader,
} from "../../catalog/CatalogKindVisuals";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import styles from "./InstalledDatasetsList.module.css";

export interface InstalledDatasetsListProps {
  datasets: DatasetCatalogItem[];
  /** In-flight installs rendered as "Adding…" rows above the installed ones. */
  installing?: PendingInstall[];
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
  const isPublished = isDatasetPublishedToCatalog(dataset);
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
          <span className={styles.installedName}>{datasetDisplayTitle(dataset)}</span>
        </div>
        <span className={styles.installedMeta}>
          {DATASET_FORMAT_LABEL[dataset.format]}
          {" · "}
          {datasetProvenanceLabel(dataset.origin, dataset.format)}
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
              publishActionTitle="Publish this dataset into the shared catalog (datasets/)"
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

/** Compact "Adding…" placeholder row matching the installed-row layout. */
function InstalledInstallingRow({ pending }: { pending: PendingInstall }) {
  return (
    <div
      className={styles.installedRow}
      role="status"
      aria-busy="true"
      aria-label={`Adding ${pending.label}`}
      style={{ opacity: 0.7 }}
    >
      <div className={styles.installedBody}>
        <div className={styles.installedHeader}>
          <FontAwesomeIcon icon={faSpinner} spin aria-hidden />
          <span className={styles.installedName}>{pending.label}</span>
        </div>
        <span className={styles.installedMeta}>Adding…</span>
      </div>
    </div>
  );
}

export const InstalledDatasetsList: React.FC<InstalledDatasetsListProps> = ({
  datasets,
  installing = [],
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
  if (datasets.length === 0 && installing.length === 0) return null;

  const label = sectionLabel ?? `Your datasets · ${datasets.length} in project`;

  return (
    <>
      <p className={styles.sectionLabel}>{label}</p>
      <div
        className={styles.installedList}
        style={refreshing ? { opacity: 0.6, pointerEvents: "none", transition: "opacity 0.15s" } : { transition: "opacity 0.15s" }}
      >
        {installing.map((pending) => (
          <InstalledInstallingRow key={`pending:${pending.key}`} pending={pending} />
        ))}
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
