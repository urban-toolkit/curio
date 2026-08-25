import React from "react";
import { CatalogBrowseDrawerShell } from "../catalog/CatalogBrowseDrawerShell";
import { CatalogBrowseDrawerBody } from "../catalog/CatalogBrowseDrawerBody";
import {
  CatalogPublishPill,
  shouldShowPublishPill,
} from "../../components/packages/CatalogPublishPill";
import {
  catalogIsFresh,
  catalogRelativeTime,
} from "../../components/catalog/catalogTimeFormat";
import { DatasetDataflowUsageSection } from "../../components/datasets/catalog/DatasetDataflowUsage";
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetDisplayTitle,
  datasetSubtitle,
  datasetProvenanceLabel,
  isDatasetPublishedToCatalog,
} from "../../services/datasetCatalog";
import { DataCatalogGeoPreview } from "./DataCatalogGeoPreview";
import { datasetCount, formatBytes, metaLeft } from "./dataHubBrowseFormat";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface DataCatalogBrowseDrawerProps {
  dataset: DatasetCatalogItem | null;
  publishingId: string | null;
  catalogPublishAllowed: boolean;
  onPublish: (dataset: DatasetCatalogItem) => void;
  onClose: () => void;
  onViewDetails: (dataset: DatasetCatalogItem) => void;
  onLayoutChange?: (slotOpen: boolean) => void;
}

export function DataCatalogBrowseDrawer({
  dataset,
  publishingId,
  catalogPublishAllowed,
  onPublish,
  onClose,
  onViewDetails,
  onLayoutChange,
}: DataCatalogBrowseDrawerProps) {
  return (
    <CatalogBrowseDrawerShell presented={dataset != null} onLayoutChange={onLayoutChange}>
      {dataset ? (
        <DataCatalogBrowseDrawerContent
          dataset={dataset}
          publishingId={publishingId}
          catalogPublishAllowed={catalogPublishAllowed}
          onPublish={onPublish}
          onClose={onClose}
          onViewDetails={onViewDetails}
        />
      ) : null}
    </CatalogBrowseDrawerShell>
  );
}

type DataCatalogBrowseDrawerContentProps = Omit<
  DataCatalogBrowseDrawerProps,
  "dataset" | "onLayoutChange"
> & { dataset: DatasetCatalogItem };

function DataCatalogBrowseDrawerContent({
  dataset,
  publishingId,
  catalogPublishAllowed,
  onPublish,
  onClose,
  onViewDetails,
}: DataCatalogBrowseDrawerContentProps) {
  const crs = dataset.schema?.crs ?? null;
  const published = isDatasetPublishedToCatalog(dataset);
  const showPublishPill = shouldShowPublishPill({
    isPublished: published,
    allowPublish: catalogPublishAllowed,
    canPublish: true,
  });

  return (
    <CatalogBrowseDrawerBody
      kind="dataset"
      headerTitle="Dataset details"
      onClose={onClose}
      hero={<DataCatalogGeoPreview dataset={dataset} />}
      title={datasetDisplayTitle(dataset)}
      badges={
        <>
          <span className={`${styles.drawerFormatBadge} ${styles[`dfmt_${dataset.format}`] || ""}`}>
            {DATASET_FORMAT_LABEL[dataset.format]}
          </span>
          {dataset.installed ? (
            <span className={styles.drawerInstalledBadge}>✓ In dataflow</span>
          ) : null}
        </>
      }
      subtitle={datasetSubtitle(dataset)}
      metaLeft={metaLeft(dataset)}
      metaRight={catalogRelativeTime(dataset.updatedAt)}
      fresh={catalogIsFresh(dataset.updatedAt)}
      description={dataset.description}
      infoLabel="Dataset info"
      infoRows={[
        { label: "Format", value: DATASET_FORMAT_LABEL[dataset.format] },
        datasetCount(dataset)
          ? {
              label: dataset.featureCount != null ? "Features" : "Rows",
              value: datasetCount(dataset),
            }
          : null,
        dataset.sizeBytes != null
          ? { label: "File size", value: formatBytes(dataset.sizeBytes) }
          : null,
        crs ? { label: "CRS", value: crs } : null,
        { label: "License", value: dataset.license || "Unknown" },
        {
          label: "Origin",
          value: datasetProvenanceLabel(dataset.origin, dataset.format),
        },
      ]}
      tags={dataset.tags}
      sections={
        /* Dataflows that consume this dataset (resolved from saved specs by the
           backend, so it works on this canvas-less browse page). Renders nothing
           when the dataset isn't used anywhere. */
        <div className={styles.drawerSection}>
          <DatasetDataflowUsageSection datasetId={dataset.id} />
        </div>
      }
      primaryAction={
        <button
          className={styles.addToPaletteBtn}
          type="button"
          onClick={() => onViewDetails(dataset)}
        >
          View details
        </button>
      }
      publishPill={
        showPublishPill ? (
          <CatalogPublishPill
            variant="hub"
            dirName={dataset.dirName || dataset.id}
            published={published}
            allowPublish={catalogPublishAllowed}
            busy={publishingId === dataset.id}
            onPublish={() => onPublish(dataset)}
            publishedTitle="Listed in the Data Catalog"
            publishActionTitle="Publish this dataset into the shared catalog (datasets/)"
          />
        ) : null
      }
    />
  );
}
