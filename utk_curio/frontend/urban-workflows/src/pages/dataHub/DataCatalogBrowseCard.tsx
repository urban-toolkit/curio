import React from "react";
import { CatalogPublishPill } from "../../components/packages/CatalogPublishPill";
import { formatDatasetLocation } from "../../components/datasets/catalog/datasetDetailHelpers";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
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
  const lastTagIdx = tags.length - 1;
  const published = isDatasetPublishedToCatalog(dataset);
  const showPublishPill = published || catalogPublishAllowed;

  return (
    <article
      className={[
        styles.card,
        selected ? styles.cardActive : "",
        styles[`card_${dataset.format}`] || "",
      ].join(" ")}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <div className={`${styles.cardStrip} ${styles[`strip_${dataset.format}`] || ""}`}>
        <span className={styles.cardFormatBadge}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {dataset.installed && <span className={styles.stripBadgePopular}>✓ INSTALLED</span>}
          {selected && <span className={styles.selectedDot} />}
        </div>
      </div>

      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>{dataset.title}</h2>
        <p className={styles.publisher}>{formatDatasetLocation(dataset)} · v1.0.0</p>
        <p
          className={styles.cardDescription}
          {...(!dataset.description ? { "aria-hidden": true } : {})}
        >
          {dataset.description || "\u00a0"}
        </p>
        <div className={styles.tagRow}>
          {tags.map((tag, i) => (
            <span
              key={tag}
              className={`${styles.tag} ${i === lastTagIdx ? styles[`tagAccent_${dataset.format}`] || "" : ""}`}
            >
              {tag}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.metaLeft}>{left}</span>
        <span className={styles.metaRight}>
          <span className={`${styles.liveDot} ${fresh ? styles.liveDotGreen : styles.liveDotGray}`} />
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
              publishActionTitle="Write this dataset into the dev catalog under datasets/"
            />
          ) : null}
        </div>
        <div className={styles.cardActionsRight}>
          <button
            className={`${styles.linkButton} ${styles[`link_${dataset.format}`] || ""}`}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onViewDetails();
            }}
          >
            View details ↗
          </button>
        </div>
      </div>
    </article>
  );
}
