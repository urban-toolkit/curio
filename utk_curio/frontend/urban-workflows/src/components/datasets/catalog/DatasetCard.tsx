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
import { CatalogPublishPill, shouldShowPublishPill } from "../../packages/CatalogPublishPill";
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

function formatAvatarClass(format: DatasetCatalogItem["format"]): string {
  return styles[`avatar_${format}` as keyof typeof styles] ?? "";
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
  onDelete?: (dataset: DatasetCatalogItem) => void;
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
  onDelete,
  onPublish,
  onOpenDetails,
}) => {
  const cardBusy = busy;
  const showUninstall = isInstalled && onUninstall != null;
  const showUnpublish = isPublished && isInstalled && onUnpublish != null;
  // Delete permanently removes an account-level computed dataset from the Data
  // Catalog (distinct from Uninstall, which only detaches it from this project).
  const isComputedAsset = dataset.origin === "computed" || Boolean(dataset.producerNodeId);
  // Never offer Delete on a pure hub row: hub rows now carry producerNodeId, so
  // a viewer browsing someone else's published dataset would otherwise see a
  // Delete button that the backend (correctly) 403s. The owner sees their own
  // asset as the merged origin="computed" row (account copy wins the dedup), so
  // their Delete affordance is unaffected. The backend publisher check is the
  // real gate; this just hides an action the user cannot perform.
  const showDelete = onDelete != null && isComputedAsset && dataset.origin !== "hub";
  const showPublishPill = shouldShowPublishPill({
    isPublished,
    allowPublish: publishAllowed,
    canPublish: onPublish != null,
  });

  const count = datasetCount(dataset);
  const time = relativeTime(dataset.updatedAt);
  const version = datasetVersion(dataset.dirName);
  const metaParts = [count, time].filter(Boolean).join(" · ");

  const sourceCaption = datasetListSourceCaption(dataset);
  const title = datasetDisplayTitle(dataset);
  const detailsLabel = `View ${title} (${DATASET_FORMAT_LABEL[dataset.format]}) details`;

  const tags = dataset.tags.length > 0 ? dataset.tags.slice(0, 2) : [sourceCaption];

  return (
    <article
      className={styles.card}
      /* Same attribute the palette rows carry (DatasetPaletteRows), so a
         card and its palette row share one identifier across surfaces. */
      data-dataset-id={dataset.id}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      {/* Format avatar */}
      <button
        type="button"
        className={`${styles.cardAvatar} ${formatAvatarClass(dataset.format)} ${styles.cardAvatarButton}`}
        title={detailsLabel}
        aria-label={detailsLabel}
        onClick={() => onOpenDetails?.(dataset)}
      >
        <CatalogKindIcon
          className={`${styles.cardIcon} ${formatAvatarClass(dataset.format)} `}
          kind="dataset"
          size="md"
          title={detailsLabel}
        />
      </button>

      {/* Body */}
      <div className={styles.cardBody}>
        {/* Presentational, like every other CatalogItemRowHeader caller
            (InstalledDatasetsList, PackageCard). Making it a second button
            named `detailsLabel` gave one card two controls with the same
            accessible name, which is both a duplicate way into the same modal
            and a strict-mode ambiguity for anything selecting by that name.
            The format avatar above is the one way in. */}
        <CatalogItemRowHeader
          kind="dataset"
          badge={
            <CatalogFormatBadge
              label={DATASET_FORMAT_LABEL[dataset.format]}
              formatKey={dataset.format}
            />
          }
        />
        <h3 className={styles.cardTitle}>{title}</h3>

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
            Add to dataflow
          </button>
        ) : null}

        {(showUninstall || showUnpublish || showDelete || showPublishPill) && (
          <div className={styles.cardSecondaryActions}>
            {showUninstall ? (
              <button
                type="button"
                className={styles.btnSecondary}
                disabled={cardBusy}
                title={`Remove ${dataset.title} from this dataflow`}
                onClick={() => onUninstall(dataset)}
              >
                Remove from dataflow
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
            {showDelete ? (
              <button
                type="button"
                className={styles.btnSecondary}
                disabled={cardBusy}
                title={`Permanently delete ${dataset.title} from your Data Catalog`}
                onClick={() => onDelete(dataset)}
              >
                Delete
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
                // Without these the pill falls back to the PACKAGE copy, so a
                // dataset offered "Publish this installed package into the
                // shared catalog (packages/)". The browse page already passes
                // the dataset wording; the canvas surfaces did not.
                publishedTitle="Listed in the Data Catalog"
                publishActionTitle="Publish this dataset into the shared catalog (datasets/)"
              />
            ) : null}
          </div>
        )}
      </div>
    </article>
  );
};
