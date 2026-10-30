import React from "react";

import DataflowThumbnail, { type ThumbnailHighlight } from "../../DataflowThumbnail";
import type { ScenarioRow } from "../../../services/scenarioCatalog";
import { ScenarioName } from "./scenarioFacts";
import styles from "../../packages/publishing/PackageCard.module.css";
import local from "./ScenarioCatalogDrawer.module.css";

export interface ScenarioCardProps {
  scenario: ScenarioRow;
  onOpenDetails?: (scenario: ScenarioRow) => void;
  /** In the In project tab: what can be done to this dataflow's scenario, a
   *  row of buttons under the card. */
  controls?: React.ReactNode;
  /** In the In project tab: the card's top-right corner, Delete. */
  corner?: React.ReactNode;
  /** In Browse all: the card's checkbox, for a drag of several. */
  check?: { checked: boolean; onChange: (on: boolean) => void };
  /** In the In project tab: the pointer entering (true) or leaving (false)
   *  the card, which marks the scenario's fixed context on the canvas. */
  onPoint?: (on: boolean) => void;
  /** The scenario's nodes marked on the graph, when they are known. */
  highlight?: ThumbnailHighlight | null;
  testId?: string;
}

/**
 * One scenario in the canvas Scenario Catalog drawer.
 *
 * The Model drawer's card body: an avatar with the way into the details
 * beneath it, a title, then the description. The set panel it sits in
 * names the set and leads to its project (`ScenarioSetGroup`). The avatar is
 * the project's graph, the picture that tells two scenarios apart; which of its
 * nodes the scenario holds shows in the details, which load them. A card is
 * never dragged: in Browse all, a set's "Pick scenarios to drag" handle drags
 * the scenarios checked on its cards, which arrive on the canvas as copies and
 * change nothing in their project. In the In project tab the scenario is
 * this dataflow's: the card marks its nodes on the graph and carries its
 * buttons.
 */
export const ScenarioCard: React.FC<ScenarioCardProps> = ({
  scenario,
  onOpenDetails,
  controls,
  corner,
  check,
  onPoint,
  highlight = null,
  testId,
}) => {
  const detailsLabel = `View ${scenario.name} (${scenario.project.name}) details`;

  return (
    <article
      className={styles.card}
      /* Same attribute the browse cards carry, so a scenario shares one
         identifier across surfaces. */
      data-scenario-key={scenario.key}
      data-testid={testId}
      onMouseEnter={onPoint ? () => onPoint(true) : undefined}
      onMouseLeave={onPoint ? () => onPoint(false) : undefined}
    >
      <div className={styles.cardAvatarCol}>
        <button
          type="button"
          className={`${styles.cardAvatar} ${styles.cardAvatarButton} ${local.avatarThumb}`}
          data-tooltip={detailsLabel}
          aria-label={detailsLabel}
          onClick={() => onOpenDetails?.(scenario)}
        >
          <DataflowThumbnail preview={scenario.preview} highlight={highlight} />
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
            onClick={() => onOpenDetails(scenario)}
          >
            View details
          </button>
        ) : null}
      </div>

      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>
          {check ? (
            <input
              type="checkbox"
              className={local.cardCheck}
              aria-label={`Select ${scenario.name}`}
              checked={check.checked}
              onChange={(e) => check.onChange(e.target.checked)}
              // A checkbox is clicked, not dragged; the card around it is.
              draggable={false}
              onClick={(e) => e.stopPropagation()}
            />
          ) : null}
          <ScenarioName row={scenario} />
        </h3>
        {scenario.description ? (
          <p className={local.cardDescription}>{scenario.description}</p>
        ) : null}
      </div>

      {corner ? <div className={local.cardCorner}>{corner}</div> : null}

      {controls ? <div className={local.cardControls}>{controls}</div> : null}
    </article>
  );
};

export default ScenarioCard;
