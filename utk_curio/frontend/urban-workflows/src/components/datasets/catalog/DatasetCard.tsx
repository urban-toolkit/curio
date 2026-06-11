import React from "react";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetListSourceCaption,
} from "../../../services/datasetCatalog";
import {
  CatalogFormatBadge,
  CatalogItemRowHeader,
  CatalogKindIcon,
} from "../../catalog/CatalogKindVisuals";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import styles from "../../packages/publishing/PackageCard.module.css";

// ── Version helper ───────────────────────────────────────────────────────────

/** Extract the ``@N`` major version from a dirName like ``computed.abc123@1``. */
function datasetVersion(dirName?: string | null): string | null {
  if (!dirName) return null;
  const m = dirName.match(/@(\d+)$/);
  return m ? `v${m[1]}` : null;
}

// ── Format helpers ───────────────────────────────────────────────────────────

function formatAccentClass(format: DatasetCatalogItem["format"]): string {
  return styles[`accent_${format}` as keyof typeof styles] ?? "";
}

// ── Count / time helpers ─────────────────────────────────────────────────────

function datasetCount(dataset: DatasetCatalogItem): string | null {
  if (dataset.featureCount != null) return `${dataset.featureCount.toLocaleString()} feat.`;
  if (dataset.rowCount != null) return `${dataset.rowCount.toLocaleString()} rows`;
  return null;
}

function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const delta = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(delta) || delta < 0) return "";
  const minutes = Math.max(1, Math.round(delta / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

// ── Props ────────────────────────────────────────────────────────────────────

export interface DatasetCardProps {
  dataset: DatasetCatalogItem;
  isInstalled: boolean;
  isPublished: boolean;
  busy: boolean;
  publishAllowed?: boolean;
  publishingId?: string | null;
  draggable?: boolean;
  onDragStart?: (event: React.DragEvent<HTMLElement>) => void;
  onDragEnd?: () => void;
  onInstall: (dataset: DatasetCatalogItem) => void;
  onUninstall?: (dataset: DatasetCatalogItem) => void;
  onUnpublish?: (dataset: DatasetCatalogItem) => void;
  onPublish?: (datasetId: string) => void;
  onOpenDetails?: (dataset: DatasetCatalogItem) => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export const DatasetCard: React.FC<DatasetCardProps> = ({
  dataset,
  isInstalled,
  isPublished,
  busy,
  publishAllowed = true,
  publishingId = null,
  draggable = true,
  onDragStart,
  onDragEnd,
  onInstall,
  onUninstall,
  onUnpublish,
  onPublish,
  onOpenDetails,
}) => {
  const cardBusy = busy;
  const showUninstall = isInstalled && onUninstall != null;
  const showUnpublish = isPublished && isInstalled && onUnpublish != null;
  const showPublishButton = onPublish != null && publishAllowed && !isPublished;
  const showPublishPill = isPublished || showPublishButton;

  const count = datasetCount(dataset);
  const time = relativeTime(dataset.updatedAt);
  const version = datasetVersion(dataset.dirName);
  const metaParts = [count, time].filter(Boolean).join(" · ");

  const upCount = dataset.producerNodeId ? 1 : 0;
  const downCount = dataset.consumerNodeIds?.length ?? 0;
  const hasConnections = upCount > 0 || downCount > 0;
  const connLabel = [
    upCount > 0 ? `${upCount}\u2191` : "",
    downCount > 0 ? `${downCount}\u2193` : "",
  ].filter(Boolean).join(" ");

  const sourceCaption = datasetListSourceCaption(dataset);

  const tags = dataset.tags.length > 0 ? dataset.tags.slice(0, 2) : [];

  return (
    <article className={styles.card}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      {/* Left accent bar */}
      {/*<div className={`${styles.cardAccent} ${formatAccentClass(dataset.format)}`} />*/}

      <div className={styles.cardIcon}>
        <CatalogKindIcon kind="dataset" size="md" title="Dataset" />
      </div>

      {/* Body */}
      <div className={styles.cardBody}>
        <CatalogItemRowHeader
          kind="dataset"
          badge={
            <CatalogFormatBadge
              label={DATASET_FORMAT_LABEL[dataset.format]}
              formatKey={dataset.format}
            />
          }
          onClick={onOpenDetails ? () => onOpenDetails(dataset) : undefined}
          buttonLabel={`View ${dataset.title} details`}
        />
        <h3 className={styles.cardTitle}>{dataset.title}</h3>

        <div className={styles.cardMetaRow}>
          
          {metaParts ? (
            <span className={styles.cardMetaText}>{metaParts}</span>
          ) : null}
          {hasConnections ? (
            <span className={styles.connBadge}>{connLabel}</span>
          ) : null}
        </div>

        {tags.length > 0 ? (
          <div className={styles.tagRow}>
            {version ? (
              <span className={styles.versionBadge}>{version}</span> 
            ) : null}
            {tags.map((tag) => (
              <span key={tag} className={styles.tag}>{tag}</span>
            ))}
          </div>
        ) : null}
      </div>

      {/* Actions */}
      <div className={styles.cardAction}>
        {!isInstalled ? (
          <button
            type="button"
            className={styles.btnInstall}
            disabled={cardBusy}
            onClick={() => onInstall(dataset)}
          >
            Install
          </button>
        ) : null}

        {(showUninstall || showUnpublish || showPublishPill) && (
          <div className={styles.cardSecondaryActions}>
            {showUninstall ? (
              <button
                type="button"
                className={styles.btnSecondary}
                disabled={cardBusy}
                title={`Remove ${dataset.title} from this dataflow`}
                onClick={() => onUninstall(dataset)}
              >
                Uninstall
              </button>
            ) : null}
            {showUnpublish ? (
              <button
                type="button"
                className={styles.btnSecondary}
                disabled={cardBusy}
                title={`Remove ${dataset.title} from the Data Catalog`}
                onClick={() => onUnpublish(dataset)}
              >
                Unpublish
              </button>
            ) : null}
            {showPublishPill ? (
              <CatalogPublishPill
                variant="hub"
                dirName={dataset.id}
                published={isPublished}
                allowPublish={publishAllowed}
                busy={publishingId === dataset.id}
                onPublish={onPublish ?? (() => {})}
              />
            ) : null}
          </div>
        )}
      </div>
    </article>
  );
};
