import React from "react";

import { CatalogKindIcon } from "../../catalog/CatalogKindVisuals";
import {
  MODEL_ORIGIN_LABEL,
  MODEL_RUNTIME_LABEL,
  isDeletableModel,
  type ModelRow,
} from "../../../services/modelCatalog";
import { modelMetaLine } from "./modelFacts";
import styles from "../../packages/publishing/PackageCard.module.css";

export interface ModelCardProps {
  model: ModelRow;
  busy: boolean;
  onDragStart?: (event: React.DragEvent<HTMLElement>) => void;
  onDragEnd?: () => void;
  onDelete?: (model: ModelRow) => void;
  onOpenDetails?: (model: ModelRow) => void;
}

/**
 * One model in the canvas Model Catalog drawer.
 *
 * The Data drawer's card body, which all three canvas drawers share: an avatar
 * with the way into the details beneath it, a title and ONE meta line. The
 * whole card is the drag source; dropping it on a node that runs a model sets
 * that node's model (`NodeContainer`). There is no "Add to project": a model is
 * named in a node's code, not installed into a dataflow.
 */
export const ModelCard: React.FC<ModelCardProps> = ({
  model,
  busy,
  onDragStart,
  onDragEnd,
  onDelete,
  onOpenDetails,
}) => {
  const detailsLabel = `View ${model.name} (${MODEL_RUNTIME_LABEL[model.runtime]}) details`;
  const showDelete = onDelete != null && isDeletableModel(model);

  return (
    <article
      className={`${styles.card} ${styles.cardDraggable}`}
      /* Same attribute the palette rows and the browse cards carry, so a
         model shares one identifier across surfaces. */
      data-model-id={model.id}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      <div className={styles.cardAvatarCol}>
        <button
          type="button"
          className={`${styles.cardAvatar} ${styles.avatar_model} ${styles.cardAvatarButton}`}
          title={detailsLabel}
          aria-label={detailsLabel}
          onClick={() => onOpenDetails?.(model)}
        >
          <CatalogKindIcon
            className={`${styles.cardIcon} ${styles.avatar_model}`}
            kind="model"
            size="md"
            title={detailsLabel}
          />
        </button>
        {onOpenDetails ? (
          <button
            type="button"
            className={styles.avatarDetailsLink}
            /* The avatar already carries `detailsLabel` as its accessible name;
               this one is hidden so the card does not expose two controls with
               the same name for the same action. */
            aria-hidden
            tabIndex={-1}
            onClick={() => onOpenDetails(model)}
          >
            View details
          </button>
        ) : null}
      </div>

      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>{model.name}</h3>
        <div className={styles.cardMetaRow}>
          <span className={styles.cardMetaText}>
            {[modelMetaLine(model), MODEL_ORIGIN_LABEL[model.origin]].join(" · ")}
          </span>
        </div>
      </div>

      <div className={styles.cardAction}>
        {showDelete ? (
          <div className={styles.cardSecondaryActions}>
            <button
              type="button"
              className={styles.btnSecondary}
              disabled={busy}
              title={`Permanently delete ${model.name} from your Model Catalog`}
              onClick={() => onDelete(model)}
            >
              Delete
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
};

export default ModelCard;
