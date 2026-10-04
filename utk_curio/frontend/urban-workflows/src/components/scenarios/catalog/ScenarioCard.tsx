import React from "react";

import DataflowThumbnail from "../../DataflowThumbnail";
import type { ScenarioRow } from "../../../services/scenarioCatalog";
import { ScenarioName, scenarioNodeCount } from "./scenarioFacts";
import styles from "../../packages/publishing/PackageCard.module.css";
import local from "./ScenarioCatalogDrawer.module.css";

export interface ScenarioCardProps {
  scenario: ScenarioRow;
  onOpenDetails?: (scenario: ScenarioRow) => void;
  onOpenProject?: (scenario: ScenarioRow) => void;
}

/**
 * One scenario in the canvas Scenario Catalog drawer.
 *
 * The Model drawer's card body: an avatar with the way into the details
 * beneath it, a title and ONE meta line, then the description. The avatar is
 * the project's graph, the picture that tells two scenarios apart; which of its
 * nodes the scenario holds shows in the details, which load them. The card is
 * not draggable, and changes nothing: a scenario is edited in its project.
 */
export const ScenarioCard: React.FC<ScenarioCardProps> = ({
  scenario,
  onOpenDetails,
  onOpenProject,
}) => {
  const detailsLabel = `View ${scenario.name} (${scenario.project.name}) details`;

  return (
    <article
      className={styles.card}
      /* Same attribute the browse cards carry, so a scenario shares one
         identifier across surfaces. */
      data-scenario-key={scenario.key}
    >
      <div className={styles.cardAvatarCol}>
        <button
          type="button"
          className={`${styles.cardAvatar} ${styles.cardAvatarButton} ${local.avatarThumb}`}
          title={detailsLabel}
          aria-label={detailsLabel}
          onClick={() => onOpenDetails?.(scenario)}
        >
          <DataflowThumbnail preview={scenario.preview} />
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

      <div className={styles.cardAction}>
        {onOpenProject ? (
          <button
            type="button"
            className={local.openLink}
            title={`Open ${scenario.project.name}, where this scenario is edited`}
            onClick={() => onOpenProject(scenario)}
          >
            Open source project
          </button>
        ) : null}
      </div>
    </article>
  );
};

export default ScenarioCard;
