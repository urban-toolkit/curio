import React from "react";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetDisplayTitle,
  datasetSubtitle,
  datasetListSourceCaption,
} from "../../../services/datasetCatalog";
import {
  CatalogFormatBadge,
  CatalogItemRowHeader,
  CatalogKindIcon,
} from "../../catalog/CatalogKindVisuals";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import {
  datasetCountCompact as datasetCount,
  relativeTimeOrEmpty as relativeTime,
} from "./datasetDetailHelpers";
import { DatasetConnectionBadge } from "./DatasetConnectionBadge";
import styles from "../../packages/publishing/PackageCard.module.css";

// ── Version helper ───────────────────────────────────────────────────────────

/** Extract the ``@N`` major version from a dirName like ``computed.abc123@1``. */
function datasetVersion(dirName?: string | null): string | null {
  if (!dirName) return null;
  const m = dirName.match(/@(\d+)$/);
  return m ? `v${m[1]}` : null;
}

// ── Format helpers ───────────────────────────────────────────────────────────
const FORMAT_ABBR: Record<DatasetCatalogItem["format"], string> = {
  geojson: "GeoJSON",
  csv: "CSV",
  json: "JSON",
  parquet: "Parquet",
  geotiff: "GeoTIFF",
  shp: "SHP",
  bundle: "Bundle",
  osm: "OSM",
};

function formatAvatarClass(format: DatasetCatalogItem["format"]): string {
  return styles[`avatar_${format}` as keyof typeof styles] ?? "";
}

function formatAccentClass(format: DatasetCatalogItem["format"]): string {
  return styles[`accent_${format}` as keyof typeof styles] ?? "";
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

  const sourceCaption = datasetListSourceCaption(dataset);

  const tags = dataset.tags.length > 0 ? dataset.tags.slice(0, 2) : [sourceCaption];

  return (
    <article
      className={styles.card}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      {/* Left accent bar */}
      <div className={`${styles.cardAccent} ${formatAccentClass(dataset.format)}`} />

      {/* Format avatar */}
      <button
        type="button"
        className={`${styles.cardAvatar} ${formatAvatarClass(dataset.format)} ${styles.cardAvatarButton}`}
        title={`View ${dataset.title} (${FORMAT_ABBR[dataset.format]}) details`}
        aria-label={`View ${dataset.title} (${FORMAT_ABBR[dataset.format]}) details`}
        onClick={() => onOpenDetails?.(dataset)}
      >
        {/* {FORMAT_ABBR[dataset.format]} */}
        <CatalogKindIcon
          className={`${styles.cardIcon} ${formatAvatarClass(dataset.format)} `}
          kind="dataset"
          size="md"
          title={`View ${dataset.title} (${FORMAT_ABBR[dataset.format]}) details`}
        />
      </button>

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
          buttonLabel={`View ${datasetDisplayTitle(dataset)} details`}
        />
        <h3 className={styles.cardTitle}>
          {datasetDisplayTitle(dataset)}
        </h3>

        <div className={styles.cardMetaRow}>
          <span className={styles.cardMetaText}>
            {datasetSubtitle(dataset)}
          </span>
          {metaParts ? <span className={styles.cardMetaText}>{metaParts}</span> : null}
          <DatasetConnectionBadge dataset={dataset} className={styles.connBadge} />
        </div>

        {tags.length > 0 ? (
          <div className={styles.tagRow}>
            {version ? <span className={styles.versionBadge}>{version}</span> : null}
            {tags.map((tag) => (
              <span key={tag} className={styles.tag}>
                {tag}
              </span>
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
