import React from "react";

import { CatalogBrowseDrawerShell } from "../catalog/CatalogBrowseDrawerShell";
import { CatalogBrowseDrawerBody } from "../catalog/CatalogBrowseDrawerBody";
import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import {
  catalogIsFresh,
  catalogRelativeTime,
} from "../../components/catalog/catalogTimeFormat";
import { modelInfoRows, modelMetaLine } from "../../components/models/catalog/modelFacts";
import {
  MODEL_ORIGIN_LABEL,
  MODEL_RUNTIME_LABEL,
  isDeletableModel,
  type ModelRow,
} from "../../services/modelCatalog";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface ModelCatalogBrowseDrawerProps {
  model: ModelRow | null;
  /** The model being deleted, so its button can say so. */
  deletingId: string | null;
  onDelete: (model: ModelRow) => void;
  onViewDetails: (model: ModelRow) => void;
  onClose: () => void;
  onLayoutChange?: (slotOpen: boolean) => void;
}

/**
 * The right-hand detail drawer on `/catalog/models`.
 *
 * Composed from `CatalogBrowseDrawerBody` like the other four; the content
 * decisions are which info rows (`modelInfoRows`, the details modal's) and one
 * action. A shipped model has no action at all, so the primary slot stays
 * empty; a downloaded one offers Delete, in the light destructive treatment,
 * and the way out comes last as on every drawer.
 */
export function ModelCatalogBrowseDrawer({
  model,
  deletingId,
  onDelete,
  onViewDetails,
  onClose,
  onLayoutChange,
}: ModelCatalogBrowseDrawerProps) {
  return (
    <CatalogBrowseDrawerShell presented={model != null} onLayoutChange={onLayoutChange}>
      {model ? (
        <CatalogBrowseDrawerBody
          kind="model"
          headerTitle="Model details"
          onClose={onClose}
          hero={
            <div className={styles.drawerKindHero}>
              <CatalogKindIcon kind="model" size="lg" title="Model" />
            </div>
          }
          title={model.name}
          badges={
            <span className={styles.drawerCategoryBadge}>
              {MODEL_RUNTIME_LABEL[model.runtime] ?? model.runtime}
            </span>
          }
          subtitle={
            <span className={styles.drawerPublisherText}>
              {model.publisher || "Unknown publisher"}
            </span>
          }
          metaLeft={modelMetaLine(model)}
          metaRight={
            model.createdAt
              ? catalogRelativeTime(model.createdAt, MODEL_ORIGIN_LABEL[model.origin])
              : MODEL_ORIGIN_LABEL[model.origin]
          }
          fresh={catalogIsFresh(model.createdAt)}
          description={model.description}
          infoLabel="Model info"
          infoRows={modelInfoRows(model)}
          tags={model.tags}
          primaryAction={
            isDeletableModel(model) ? (
              <button
                className={styles.destructiveBtn}
                type="button"
                disabled={deletingId === model.id}
                title={`Permanently delete ${model.name} from your Model Catalog`}
                onClick={() => onDelete(model)}
              >
                {deletingId === model.id ? "Deleting…" : "Delete"}
              </button>
            ) : null
          }
          secondaryAction={
            <button
              className={styles.drawerLinkButton}
              type="button"
              onClick={() => onViewDetails(model)}
            >
              View details
            </button>
          }
        />
      ) : null}
    </CatalogBrowseDrawerShell>
  );
}

export default ModelCatalogBrowseDrawer;
