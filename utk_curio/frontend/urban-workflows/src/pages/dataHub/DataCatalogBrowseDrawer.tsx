import React from "react";
import { CatalogDrawerTitle } from "../../components/catalog/CatalogKindVisuals";
import { formatDatasetLocation } from "../../components/datasets/catalog/datasetDetailHelpers";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetProvenanceLabel,
  isDatasetPublishedToCatalog,
} from "../../services/datasetCatalog";
import { DataCatalogGeoPreview } from "./DataCatalogGeoPreview";
import { datasetCount, formatBytes, isFresh, metaLeft, relativeTime } from "./dataHubBrowseFormat";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface DataCatalogBrowseDrawerProps {
  dataset: DatasetCatalogItem | null;
  publishingId: string | null;
  onPublish: (dataset: DatasetCatalogItem) => void;
}

export function DataCatalogBrowseDrawer({
  dataset,
  publishingId,
  onPublish,
}: DataCatalogBrowseDrawerProps) {
  if (!dataset) {
    return (
      <aside className={styles.browseDrawer}>
        <div className={styles.drawerHeader}>
          <CatalogDrawerTitle kind="dataset" title="Dataset details" />
          <button className={styles.drawerClose} type="button">
            ✕
          </button>
        </div>
        <div className={styles.drawerEmpty}>Select a dataset to see details</div>
      </aside>
    );
  }

  const fresh = isFresh(dataset.updatedAt);
  const left = metaLeft(dataset);
  const crs = dataset.schema?.crs ?? null;
  const published = isDatasetPublishedToCatalog(dataset);

  return (
    <aside className={styles.browseDrawer}>
      <div className={styles.drawerHeader}>
        <CatalogDrawerTitle kind="dataset" title="Dataset details" />
        <button className={styles.drawerClose} type="button" aria-label="Close">
          ✕
        </button>
      </div>

      <DataCatalogGeoPreview format={dataset.format} />

      <div className={styles.drawerDatasetName}>
        <h2>{dataset.title}</h2>
        <div className={styles.drawerBadgesRow}>
          <span className={`${styles.drawerFormatBadge} ${styles[`dfmt_${dataset.format}`] || ""}`}>
            {DATASET_FORMAT_LABEL[dataset.format]}
          </span>
          {published ? (
            <span className={styles.drawerPublishStatusPublished}>Published</span>
          ) : (
            <span className={styles.drawerPublishStatusUnpublished}>Unpublished</span>
          )}
          {dataset.installed && (
            <span className={`${styles.drawerFormatBadge} ${styles.dfmt_geojson}`}>✓ Installed</span>
          )}
        </div>
      </div>

      <div className={styles.drawerPublisher}>
        <span className={styles.drawerPublisherText}>
          {formatDatasetLocation(dataset)} · v1.0.0
        </span>
        <span className={styles.verifiedBadge}>
          <span className={styles.verifiedCircle}>✓</span>
          Verified
        </span>
      </div>

      <div className={styles.drawerMeta}>
        <span>{left}</span>
        <span className={styles.drawerMetaRight}>
          <span className={`${styles.liveDot} ${fresh ? styles.liveDotGreen : styles.liveDotGray}`} />
          <span>{relativeTime(dataset.updatedAt)}</span>
        </span>
      </div>

      {dataset.description && (
        <div className={styles.drawerSection}>
          <p className={styles.drawerDescription}>{dataset.description}</p>
        </div>
      )}

      <div className={styles.drawerSection}>
        <p className={styles.drawerSectionLabel}>Dataset Info</p>
        <div className={styles.infoRow}>
          <span className={styles.infoRowLabel}>Format</span>
          <span className={styles.infoRowValue}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
        </div>
        {datasetCount(dataset) && (
          <div className={styles.infoRow}>
            <span className={styles.infoRowLabel}>
              {dataset.featureCount != null ? "Features" : "Rows"}
            </span>
            <span className={styles.infoRowValue}>{datasetCount(dataset)}</span>
          </div>
        )}
        {dataset.sizeBytes != null && (
          <div className={styles.infoRow}>
            <span className={styles.infoRowLabel}>File size</span>
            <span className={styles.infoRowValue}>{formatBytes(dataset.sizeBytes)}</span>
          </div>
        )}
        {crs && (
          <div className={styles.infoRow}>
            <span className={styles.infoRowLabel}>CRS</span>
            <span className={styles.infoRowValue}>{crs}</span>
          </div>
        )}
        <div className={styles.infoRow}>
          <span className={styles.infoRowLabel}>License</span>
          <span className={styles.infoRowValue}>{dataset.license || "CC BY 4.0"}</span>
        </div>
        <div className={styles.infoRow}>
          <span className={styles.infoRowLabel}>Origin</span>
          <span className={styles.infoRowValue}>
            {datasetProvenanceLabel(dataset.origin, dataset.format)}
          </span>
        </div>
      </div>

      {dataset.tags.length > 0 && (
        <div className={styles.drawerSection}>
          <p className={styles.drawerSectionLabel}>Tags</p>
          <div className={styles.drawerTagsRow}>
            {dataset.tags.map((tag) => (
              <span key={tag} className={styles.drawerTag}>
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className={styles.drawerCtas}>
        {published ? (
          <div className={styles.drawerPublishedPrimary} role="status" aria-label="Published to Data Catalog">
            Published
          </div>
        ) : (
          <button
            type="button"
            className={styles.addToPaletteBtn}
            disabled={publishingId != null}
            onClick={() => onPublish(dataset)}
          >
            Publish
          </button>
        )}
        <button className={styles.viewSampleBtn} type="button">
          View sample data
        </button>
      </div>

      <p className={styles.trustNote}>
        Published by verified author
        <br />
        Last updated: {relativeTime(dataset.updatedAt)}
      </p>
    </aside>
  );
}
