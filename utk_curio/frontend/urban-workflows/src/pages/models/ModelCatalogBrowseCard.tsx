import React from "react";

import { CatalogItemStripHeader } from "../../components/catalog/CatalogKindVisuals";
import { modelLabelCount, modelSizeLabel } from "../../components/models/catalog/modelFacts";
import {
  MODEL_ORIGIN_LABEL,
  MODEL_RUNTIME_LABEL,
  type ModelRow,
} from "../../services/modelCatalog";
import styles from "../catalog/CatalogBrowseLayout.module.css";
import cardStyles from "./ModelCatalogBrowseCard.module.css";

export interface ModelCatalogBrowseCardProps {
  model: ModelRow;
  selected: boolean;
  onSelect: () => void;
  onViewDetails: () => void;
  /** Right-click. The grid owns the menu; the card reports and selects, which
   *  is what a left-click does too. Same division as the peer pages. */
  onContextMenu?: (e: React.MouseEvent) => void;
}

/**
 * One model in the `/catalog/models` grid.
 *
 * Structurally identical to `DiscoverySourceCard`, `DataCatalogBrowseCard` and
 * their peers, and painted from the same stylesheet: strip header, body, tag
 * row, meta row, actions. The strip carries the runtime as its badge; the
 * origin is the card's status, at the start of its actions row.
 */
export function ModelCatalogBrowseCard({
  model,
  selected,
  onSelect,
  onViewDetails,
  onContextMenu,
}: ModelCatalogBrowseCardProps) {
  const tags = model.tags.slice(0, 3);
  const meta = [modelLabelCount(model), modelSizeLabel(model)].filter(Boolean).join(" · ");

  return (
    <article
      className={[
        styles.card,
        selected ? styles.cardActive : "",
        selected ? cardStyles.cardActive : "",
        cardStyles.card_model,
      ]
        .filter(Boolean)
        .join(" ")}
      data-model-id={model.id}
      role="button"
      tabIndex={0}
      onContextMenu={onContextMenu}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <div className={`${styles.cardStrip} ${cardStyles.strip_model}`}>
        <CatalogItemStripHeader
          kind="model"
          badge={
            <span className={styles.cardFormatBadge}>
              {MODEL_RUNTIME_LABEL[model.runtime] ?? model.runtime}
            </span>
          }
        />
      </div>

      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>{model.name}</h2>
        <p className={styles.publisher}>{model.publisher || "Unknown publisher"}</p>
        {/* The non-breaking space keeps a description-less card the same height
            as its neighbours, as the peer cards do. */}
        <p
          className={styles.cardDescription}
          {...(!model.description ? { "aria-hidden": true } : {})}
        >
          {model.description || " "}
        </p>
        <div className={styles.tagRow} data-curio-tag-row="true">
          {tags.map((tag) => (
            <span key={tag} className={styles.tag} data-curio-tag-chip="true">
              {tag}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.metaLeft}>{meta}</span>
        <span className={styles.metaRight}>{model.license || "Unknown license"}</span>
      </div>

      <div className={styles.cardActions}>
        {/* "View details" is the peers' one way in. Delete is a decision about
            the account, so it lives in the drawer and the menu, as the other
            catalogs' account-level actions do. */}
        <div className={styles.cardActionsLeft}>
          <span className={`${styles.cardStatus} ${styles.cardStatusMuted}`}>
            {MODEL_ORIGIN_LABEL[model.origin]}
          </span>
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

export default ModelCatalogBrowseCard;
