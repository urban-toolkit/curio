import React from "react";
import {
  DATASET_FORMAT_LABEL,
  DATASET_ORIGIN_LABEL,
  DatasetCatalogItem,
} from "../../../services/datasetCatalog";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import styles from "./DatasetCard.module.css";

const CARD_ICON_VARIANTS = [
  styles.cardIconWarm,
  styles.cardIconCool,
  styles.cardIconViolet,
] as const;

function iconVariantForDataset(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash + id.charCodeAt(i)) % CARD_ICON_VARIANTS.length;
  }
  return CARD_ICON_VARIANTS[hash]!;
}

function initials(title: string): string {
  const words = title.trim().split(/\s+/).filter(Boolean);
  const seed = words.length > 1 ? `${words[0][0]}${words[1][0]}` : title.slice(0, 2);
  return seed.toUpperCase();
}

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
  const publisher = dataset.sourceLabel || DATASET_ORIGIN_LABEL[dataset.origin];
  const tags = dataset.tags.length > 0 ? dataset.tags.slice(0, 2) : [dataset.format, "data"];

  return (
    <article
      className={`${styles.card} ${draggable ? styles.cardDraggable : ""}`}
      draggable={draggable}
      onDragStart={onDragStart}
    >
      <button
        type="button"
        className={`${styles.cardIcon} ${iconVariantForDataset(dataset.id)} ${styles.cardIconButton}`}
        title={`View ${dataset.title} details`}
        aria-label={`View ${dataset.title} details`}
        onClick={() => onOpenDetails?.(dataset)}
      >
        {initials(dataset.title)}
      </button>

      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>{dataset.title}</h3>
        <p className={styles.cardMeta}>
          {publisher} · v1.0.0{dataset.license ? ` · ${dataset.license}` : " · MIT"}
        </p>
        <div className={styles.tagRow}>
          <span className={styles.tag}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
          {tags.map((tag) => (
            <span key={tag} className={styles.tag}>{tag}</span>
          ))}
        </div>
      </div>

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
