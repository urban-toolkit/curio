import React from "react";

import DataflowThumbnail from "../../components/DataflowThumbnail";
import { CatalogItemStripHeader } from "../../components/catalog/CatalogKindVisuals";
import { catalogRelativeTime } from "../../components/catalog/catalogTimeFormat";
import {
  scenarioNodeCount,
  scenarioOriginLabel,
} from "../../components/scenarios/catalog/scenarioFacts";
import type { ScenarioRow } from "../../services/scenarioCatalog";
import styles from "../catalog/CatalogBrowseLayout.module.css";
import cardStyles from "./ScenarioCatalogBrowseCard.module.css";

export interface ScenarioCatalogBrowseCardProps {
  scenario: ScenarioRow;
  selected: boolean;
  onSelect: () => void;
  onViewDetails: () => void;
  /** Right-click. The grid owns the menu; the card reports and selects, which
   *  is what a left-click does too. Same division as the peer pages. */
  onContextMenu?: (e: React.MouseEvent) => void;
}

/**
 * One scenario in the `/catalog/scenarios` grid.
 *
 * Structurally the Model Catalog's card, painted from the same stylesheet:
 * strip header, body, meta row, actions, with the project's graph between the
 * strip and the body. The strip wears the scenario's colour; its origin is the
 * card's status, at the start of its actions row.
 */
export function ScenarioCatalogBrowseCard({
  scenario,
  selected,
  onSelect,
  onViewDetails,
  onContextMenu,
}: ScenarioCatalogBrowseCardProps) {
  // When its project was last saved: a scenario changes with its project.
  const edited = catalogRelativeTime(scenario.project.updatedAt, "");

  return (
    <article
      className={[
        styles.card,
        selected ? styles.cardActive : "",
        selected ? cardStyles.cardActive : "",
        cardStyles.card_scenario,
      ]
        .filter(Boolean)
        .join(" ")}
      style={{ "--scenario-color": scenario.color } as React.CSSProperties}
      data-scenario-key={scenario.key}
      role="button"
      tabIndex={0}
      onContextMenu={onContextMenu}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <div className={`${styles.cardStrip} ${cardStyles.strip_scenario}`}>
        <CatalogItemStripHeader kind="scenario" />
      </div>

      <div className={cardStyles.thumbnail}>
        <DataflowThumbnail preview={scenario.preview} />
      </div>

      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>{scenario.name}</h2>
        <p className={styles.publisher}>{scenario.project.name}</p>
        {/* The non-breaking space keeps a description-less card the same height
            as its neighbours, as the peer cards do. */}
        <p
          className={styles.cardDescription}
          {...(!scenario.description ? { "aria-hidden": true } : {})}
        >
          {scenario.description || " "}
        </p>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.metaLeft}>{scenarioNodeCount(scenario)}</span>
        <span className={styles.metaRight}>{edited ? `Edited ${edited}` : null}</span>
      </div>

      <div className={styles.cardActions}>
        {/* "View details" is the peers' one way in. Opening the project leaves
            the page, so it lives in the drawer and the menu. */}
        <div className={styles.cardActionsLeft}>
          <span className={`${styles.cardStatus} ${styles.cardStatusMuted}`}>
            {scenarioOriginLabel(scenario)}
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

export default ScenarioCatalogBrowseCard;
