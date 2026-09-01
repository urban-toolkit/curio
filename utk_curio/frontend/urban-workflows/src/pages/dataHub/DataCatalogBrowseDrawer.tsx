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
import {
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetDisplayTitle,
  datasetSubtitle,
  datasetProvenanceLabel,
  isDatasetPublishedToCatalog,
  isUserOwnedDataset,
} from "../../services/datasetCatalog";
import { DataCatalogGeoPreview } from "./DataCatalogGeoPreview";
import { datasetCount, formatBytes, metaLeft } from "./dataHubBrowseFormat";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface DataCatalogBrowseDrawerProps {
  dataset: DatasetCatalogItem | null;
  publishingId: string | null;
  catalogPublishAllowed: boolean;
  onPublish: (dataset: DatasetCatalogItem) => void;
  onUnpublish: (dataset: DatasetCatalogItem) => void;
  inAllProjects?: boolean;
  defaultsBusy?: boolean;
  onAddToAllProjects: (dataset: DatasetCatalogItem) => void;
  onRemoveFromAllProjects: (dataset: DatasetCatalogItem) => void;
  onClose: () => void;
  onViewDetails: (dataset: DatasetCatalogItem) => void;
  onLayoutChange?: (slotOpen: boolean) => void;
}

export function DataCatalogBrowseDrawer({
  dataset,
  publishingId,
  catalogPublishAllowed,
  onPublish,
  onUnpublish,
  inAllProjects = false,
  defaultsBusy = false,
  onAddToAllProjects,
  onRemoveFromAllProjects,
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
          onUnpublish={onUnpublish}
          inAllProjects={inAllProjects}
          defaultsBusy={defaultsBusy}
          onAddToAllProjects={onAddToAllProjects}
          onRemoveFromAllProjects={onRemoveFromAllProjects}
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
  onUnpublish,
  inAllProjects = false,
  defaultsBusy = false,
  onAddToAllProjects,
  onRemoveFromAllProjects,
  onClose,
  onViewDetails,
}: DataCatalogBrowseDrawerContentProps) {
  const crs = dataset.schema?.crs ?? null;
  const published = isDatasetPublishedToCatalog(dataset);
  const showPublishPill = shouldShowPublishPill({
    isPublished: published,
    allowPublish: catalogPublishAllowed,
    // `true` here meant every dataset offered to publish itself back into the
    // catalog it shipped from, and - once published - offered to unpublish
    // something the user never published and cannot withdraw. Its two peers
    // always gated on ownership (`pkg.readOnly !== true`, `agent.publishable`);
    // this one did not. `isUserOwnedDataset` reads the store folder, which does
    // not move when installing flips `origin` from hub to imported.
    canPublish: isUserOwnedDataset(dataset),
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
            <span className={styles.drawerInstalledBadge}>✓ In project</span>
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
      /* No "Used in projects" list. It fired a per-dataset `/usage` request that
         walks every project's spec, from a panel that opens on the first card
         the moment the page loads - and it answered a question this page does
         not ask. The full details view still carries the usage, where someone
         has actually asked about this one dataset. Its two peers show nothing
         equivalent. */
      primaryAction={
        /* The page has no project, so the only add it CAN offer is the
           account-level one - which is why the Data Catalog had no action here
           at all until datasets grew a defaults list. Same vocabulary as its
           peers: dark to add, light to take away. */
        inAllProjects ? (
          <button
            className={styles.destructiveBtn}
            type="button"
            disabled={defaultsBusy}
            title={`Detach ${datasetDisplayTitle(dataset)} from every project. The dataset stays in your catalog.`}
            onClick={() => onRemoveFromAllProjects(dataset)}
          >
            {defaultsBusy ? "Removing…" : "Remove from all projects"}
          </button>
        ) : (
          <button
            className={styles.addToPaletteBtn}
            type="button"
            disabled={defaultsBusy}
            title={`Add ${datasetDisplayTitle(dataset)} to every project you have, and to new ones`}
            onClick={() => onAddToAllProjects(dataset)}
          >
            {defaultsBusy ? "Adding…" : "Add to all projects"}
          </button>
        )
      }
      secondaryAction={
        /* Kept, in the slot below the primary. The drawer's primary used to BE
           "View details", which left the page with no account-level action at
           all; that is now the primary, and this moves down rather than away.
           `datasetDetailEntryPoints` holds the rule that the card and the
           drawer offer the same one, under the same name. */
        <button
          className={styles.drawerLinkButton}
          type="button"
          onClick={() => onViewDetails(dataset)}
        >
          View details
        </button>
      }
      publishPill={
        showPublishPill ? (
          <CatalogPublishPill
            /* Not "hub": this sits directly under "Add to all projects", and
               the card-sized pill left a stubby button below a full-width one. */
            variant="drawer"
            dirName={dataset.dirName || dataset.id}
            published={published}
            allowPublish={catalogPublishAllowed}
            busy={publishingId === dataset.id}
            onPublish={() => onPublish(dataset)}
            onUnpublish={() => onUnpublish(dataset)}
            publishActionTitle="Publish this dataset into the shared catalog (datasets/)"
            unpublishActionTitle={`Remove ${datasetDisplayTitle(dataset)} from the Data Catalog`}
            itemLabel={datasetDisplayTitle(dataset)}
            catalogLabel="the Data Catalog"
          />
        ) : null
      }
    />
  );
}
