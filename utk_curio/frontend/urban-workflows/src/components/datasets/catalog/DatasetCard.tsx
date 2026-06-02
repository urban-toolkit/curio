import React from "react";
import {
  DatasetCatalogItem,
  DatasetFormat,
} from "../../../services/datasetCatalog";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import styles from "./DatasetCard.module.css";

// ── Format helpers ───────────────────────────────────────────────────────────

const FORMAT_ABBR: Record<DatasetFormat, string> = {
  geojson: "GeoJSON",
  csv: "CSV",
  json: "JSON",
  parquet: "Parquet",
  geotiff: "GeoTIFF",
  shp: "SHP",
};

function formatAvatarClass(format: DatasetFormat): string {
  return styles[`avatar_${format}` as keyof typeof styles] ?? "";
}

function formatAccentClass(format: DatasetFormat): string {
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
  const metaParts = [count, time].filter(Boolean).join(" · ");

  const upCount = dataset.producerNodeId ? 1 : 0;
  const downCount = dataset.consumerNodeIds?.length ?? 0;
  const hasConnections = upCount > 0 || downCount > 0;
  const connLabel = [
    upCount > 0 ? `${upCount}\u2191` : "",
    downCount > 0 ? `${downCount}\u2193` : "",
  ].filter(Boolean).join(" ");

  const tags = dataset.tags.length > 0 ? dataset.tags.slice(0, 2) : [];

  return (
    <article
      className={`${styles.card} ${draggable ? styles.cardDraggable : ""}`}
      draggable={draggable}
      onDragStart={onDragStart}
    >
      {/* Left accent bar */}
      <div className={`${styles.cardAccent} ${formatAccentClass(dataset.format)}`} />

      {/* Format avatar */}
      <button
        type="button"
        className={`${styles.cardAvatar} ${formatAvatarClass(dataset.format)} ${styles.cardAvatarButton}`}
        title={`View ${dataset.title} details`}
        aria-label={`View ${dataset.title} details`}
        onClick={() => onOpenDetails?.(dataset)}
      >
        {FORMAT_ABBR[dataset.format]}
      </button>

      {/* Body */}
      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>{dataset.title}</h3>

        {dataset.sourceLabel ? (
          <p className={styles.cardSource}>{dataset.sourceLabel}</p>
        ) : null}

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
                title={`Remove ${dataset.title} from the Data Hub`}
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
