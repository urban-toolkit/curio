import React from "react";

import DataflowThumbnail, { type ThumbnailHighlight } from "../../DataflowThumbnail";
import type { ScenarioRow } from "../../../services/scenarioCatalog";
import { ScenarioName, scenarioNodeCount } from "./scenarioFacts";
import styles from "../../packages/publishing/PackageCard.module.css";
import local from "./ScenarioCatalogDrawer.module.css";

export interface ScenarioCardProps {
  scenario: ScenarioRow;
  onOpenDetails?: (scenario: ScenarioRow) => void;
  /** In the In project tab: what can be done to this dataflow's scenario, a
   *  row of buttons under the card. */
  controls?: React.ReactNode;
  /** In Browse all: the card's drag, which brings its scenario. */
  onDragStart?: (event: React.DragEvent<HTMLElement>) => void;
  onDragEnd?: () => void;
  /** In the In project tab: the pointer entering (true) or leaving (false)
   *  the card, which marks the scenario's shared context and shared outcomes
   *  on the canvas. */
  onPoint?: (on: boolean) => void;
  /** The scenario's nodes marked on the graph, when they are known. */
  highlight?: ThumbnailHighlight | null;
  testId?: string;
}

/**
 * One scenario in the canvas Scenario Catalog drawer.
 *
 * The Model drawer's card body: an avatar with the way into the details
 * beneath it, a title and ONE meta line, then the description. The set panel
 * it sits in names the set and leads to its project (`ScenarioSetGroup`). The
 * avatar is the project's graph, the picture that tells two scenarios apart.
 * In Browse all the card drags its scenario onto the canvas, as every
 * catalog's card drags one item; the copy changes nothing in its project. In
 * the In project tab the scenario is this dataflow's: the card marks its nodes
 * on the graph and carries its buttons.
 */
export const ScenarioCard: React.FC<ScenarioCardProps> = ({
  scenario,
  onOpenDetails,
  controls,
  onDragStart,
  onDragEnd,
  onPoint,
  highlight = null,
  testId,
}) => {
  const detailsLabel = `View ${scenario.name} (${scenario.project.name}) details`;
  const draggable = Boolean(onDragStart);

  return (
    <article
      className={draggable ? `${styles.card} ${styles.cardDraggable}` : styles.card}
      /* Same attribute the browse cards carry, so a scenario shares one
         identifier across surfaces. */
      data-scenario-key={scenario.key}
      data-testid={testId}
      draggable={draggable || undefined}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
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
          <ScenarioName row={scenario} />
        </h3>
        <div className={styles.cardMetaRow}>
          <span className={styles.cardMetaText}>
            {[scenario.project.name, scenarioNodeCount(scenario)].join(" · ")}
          </span>
        </div>
        {scenario.description ? (
          <p className={local.cardDescription}>{scenario.description}</p>
        ) : null}
      </div>

      {controls ? <div className={local.cardControls}>{controls}</div> : null}
    </article>
  );
};

export default ScenarioCard;
