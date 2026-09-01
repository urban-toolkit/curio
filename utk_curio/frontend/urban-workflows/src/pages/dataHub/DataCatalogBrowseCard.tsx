import React from "react";
import { CatalogItemStripHeader } from "../../components/catalog/CatalogKindVisuals";
import {
  CatalogPublishPill,
  shouldShowPublishPill,
} from "../../components/packages/CatalogPublishPill";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetDisplayTitle,
  datasetSubtitle,
  isDatasetPublishedToCatalog,
} from "../../services/datasetCatalog";
import { isFresh, metaLeft, relativeTime } from "./dataHubBrowseFormat";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface DataCatalogBrowseCardProps {
  dataset: DatasetCatalogItem;
  selected: boolean;
  onSelect: () => void;
  onViewDetails: () => void;
  publishingId: string | null;
  onPublish: (dataset: DatasetCatalogItem) => void;
  catalogPublishAllowed: boolean;
}

export function DataCatalogBrowseCard({
  dataset,
  selected,
  onSelect,
  onViewDetails,
  publishingId,
  onPublish,
  catalogPublishAllowed,
}: DataCatalogBrowseCardProps) {
  const fresh = isFresh(dataset.updatedAt);
  const left = metaLeft(dataset);
  const tags = dataset.tags.length > 0 ? dataset.tags.slice(0, 3) : [dataset.format];
  const published = isDatasetPublishedToCatalog(dataset);
  const showPublishPill = shouldShowPublishPill({
    isPublished: published,
    allowPublish: catalogPublishAllowed,
    canPublish: true,
  });

  return (
    <article
      className={[
        styles.card,
        selected ? styles.cardActive : "",
        styles[`card_${dataset.format}`] || "",
      ].join(" ")}
      // The cross-surface identity attribute the drawer card and the tools
      // palette already carry, and which test_frontend/README.md says every
      // card root has. This one did not, so nothing could address a browse
      // card except by its display copy.
      data-dataset-id={dataset.id}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <div className={`${styles.cardStrip} ${styles[`strip_${dataset.format}`] || ""}`}>
        <CatalogItemStripHeader
          kind="dataset"
          badge={
            <span className={styles.cardFormatBadge}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
          }
          trailing={
            dataset.installed ? (
              <span className={styles.stripBadgePopular}>✓ In dataflow</span>
            ) : null
          }
        />
      </div>

      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>
          {datasetDisplayTitle(dataset)}
        </h2>
        <p className={styles.publisher}>
          {datasetSubtitle(dataset)}
          {/*{formatDatasetLocation(dataset)} · v1.0.0*/}
        </p>
        <p
          className={styles.cardDescription}
          {...(!dataset.description ? { "aria-hidden": true } : {})}
        >
          {dataset.description || "\u00a0"}
        </p>
        <div className={styles.tagRow}>
          {tags.map((tag) => (
            <span key={tag} className={styles.tag}>
              {tag}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.metaLeft}>{left}</span>
        <span className={styles.metaRight}>
          <span
            className={`${styles.liveDot} ${fresh ? styles.liveDotGreen : styles.liveDotGray}`}
          />
          <span>{relativeTime(dataset.updatedAt)}</span>
        </span>
      </div>

      <div className={styles.cardActions}>
        <div className={styles.cardActionsLeft}>
          {showPublishPill ? (
            <CatalogPublishPill
              variant="hub"
              dirName={dataset.dirName || dataset.id}
              published={published}
              allowPublish={catalogPublishAllowed}
              busy={publishingId === dataset.id}
              onPublish={() => {
                void onPublish(dataset);
              }}
              publishedTitle="Listed in the Data Catalog"
              publishActionTitle="Publish this dataset into the shared catalog (datasets/)"
            />
          ) : null}
        </div>
        <div className={styles.cardActionsRight}>
          <button
            className={styles.linkButton}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onViewDetails();
            }}
          >
            View details
          </button>
        </div>
      </div>
    </article>
  );
}
