import React from "react";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetDisplayTitle,
  datasetSubtitle,
  datasetListSourceCaption,
} from "../../../services/datasetCatalog";
import {
  CatalogKindIcon,
} from "../../catalog/CatalogKindVisuals";
import {
  isSharedCatalogDataset,
  isUserOwnedDataset,
} from "../../../services/datasetCatalog";
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
  busy: boolean;
  draggable?: boolean;
  onDragStart?: (event: React.DragEvent<HTMLElement>) => void;
  onDragEnd?: () => void;
  onInstall: (dataset: DatasetCatalogItem) => void;
  onUninstall?: (dataset: DatasetCatalogItem) => void;
  /** False in a dataflow that has not been saved yet: there is no project to
   *  remove from, so the control shows disabled rather than vanishing. */
  hasProject?: boolean;
  onDelete?: (dataset: DatasetCatalogItem) => void;
  onOpenDetails?: (dataset: DatasetCatalogItem) => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export const DatasetCard: React.FC<DatasetCardProps> = ({
  dataset,
  isInstalled,
  busy,
  draggable = true,
  onDragStart,
  onDragEnd,
  onInstall,
  onUninstall,
  hasProject = true,
  onDelete,
  onOpenDetails,
}) => {
  const cardBusy = busy;
  const showUninstall = isInstalled && onUninstall != null;
  // Delete permanently removes an account-level computed dataset from the Data
  // Catalog (distinct from Uninstall, which only detaches it from this project).
  const isComputedAsset = dataset.origin === "computed" || Boolean(dataset.producerNodeId);
  // Never offer Delete on something that came from the shared catalog: those
  // rows carry producerNodeId, so `isComputedAsset` alone would light up a
  // Delete button the backend (correctly) 403s.
  //
  // `origin !== "hub"` used to be the guard and did not hold: INSTALLING a
  // catalog dataset flips its origin from "hub" to "imported" while it keeps
  // its `data.*` store folder, so a published-computed dataset the user merely
  // installed slipped past and offered Delete. The store folder is the durable
  // signal - the same one publish now uses.
  // A file the user uploaded is an account-level asset just as much as a node
  // output is, and the one they are most likely to want rid of on purpose. It
  // used to have no Delete at all: the only way to remove it was to remove it
  // from the last dataflow using it, which deleted it as a side effect of a
  // differently-named action.
  const isOwnUpload =
    String(dataset.dirName ?? "").startsWith("imported.") ||
    dataset.origin === "imported";
  const showDelete =
    onDelete != null &&
    (isComputedAsset || isOwnUpload) &&
    !isSharedCatalogDataset(dataset);

  const count = datasetCount(dataset);
  const time = relativeTime(dataset.updatedAt);
  const version = datasetVersion(dataset.dirName);
  const metaParts = [count, time].filter(Boolean).join(" · ");

  const sourceCaption = datasetListSourceCaption(dataset);
  const title = datasetDisplayTitle(dataset);
  const detailsLabel = `View ${title} (${DATASET_FORMAT_LABEL[dataset.format]}) details`;


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
      {/* Format avatar, and the way in directly beneath it. */}
      <div className={styles.cardAvatarCol}>
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
        {onOpenDetails ? (
          <button
            type="button"
            className={styles.avatarDetailsLink}
            /* The avatar already carries `detailsLabel` as its accessible name;
               this one is hidden from the a11y tree so the card does not expose
               two controls with the same name for the same action. */
            aria-hidden
            tabIndex={-1}
            onClick={() => onOpenDetails(dataset)}
          >
            View details
          </button>
        ) : null}
      </div>

      {/* Body */}
      {/* The Agent drawer's card body, the baseline all three now share: a
          title and ONE meta line. This carried a `CatalogItemRowHeader` strip
          and a tag row on top of its meta row - three rows of chrome around one
          dataset name.

          Nothing informative was dropped, only re-sited: the format, the row
          count, the update time and the source all read as meta text. The
          connection badge stays a badge, because - like the package card's
          update chip - it is live state rather than description. */}
      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>{title}</h3>

        <div className={styles.cardMetaRow}>
          <span className={styles.cardMetaText}>
            {[
              DATASET_FORMAT_LABEL[dataset.format],
              version,
              datasetSubtitle(dataset),
              metaParts,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
          <DatasetConnectionBadge dataset={dataset} className={styles.connBadge} />
        </div>
      </div>

      {/* Actions */}
      <div className={styles.cardAction}>
        {!isInstalled ? (
          <button
            type="button"
            className={styles.btnInstall}
            disabled={cardBusy}
            /* Its Remove twin has had a tooltip in both states since this pair
               was evened up; Add had none on either the Data or the Node card,
               while the Agent card had one. Three buttons, two conventions. */
            title={`Add ${dataset.title} to this project`}
            onClick={() => onInstall(dataset)}
          >
            Add to project
          </button>
        ) : null}

        {/* Publishing is not a card action on any surface. It is an
            account-level decision about one item, and it belongs where the
            other decisions about that item are: the Data Catalog page's detail
            drawer. On a card it competed with the card's identity and put a
            deployment-wide write one click from a browse gesture. */}
        {(showUninstall || showDelete) && (
          // Order is the vocabulary made visible: actions first (dark), then
          // the destructive ones (light), with Delete last of all so the most
          // final thing on the card is the furthest from the first thing.
          <div className={styles.cardSecondaryActions}>
            {showUninstall ? (
              <button
                type="button"
                className={styles.btnSecondary}
                disabled={cardBusy || !hasProject}
                title={
                  hasProject
                    ? `Remove ${dataset.title} from this project`
                    : "Save this dataflow first. There is no project to remove it from yet."
                }
                onClick={() => onUninstall(dataset)}
              >
                Remove from project
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
          </div>
        )}
      </div>
    </article>
  );
};
