import React from "react";

import { CatalogBrowseDrawerShell } from "../catalog/CatalogBrowseDrawerShell";
import { CatalogBrowseDrawerBody } from "../catalog/CatalogBrowseDrawerBody";
import DataflowThumbnail from "../../components/DataflowThumbnail";
import {
  catalogIsFresh,
  catalogRelativeTime,
} from "../../components/catalog/catalogTimeFormat";
import {
  ScenarioSwatch,
  scenarioHighlight,
  scenarioInfoRows,
  scenarioNodeCount,
  scenarioOriginLabel,
} from "../../components/scenarios/catalog/scenarioFacts";
import { useScenarioDetails, type ScenarioRow } from "../../services/scenarioCatalog";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface ScenarioCatalogBrowseDrawerProps {
  scenario: ScenarioRow | null;
  onOpenProject: (scenario: ScenarioRow) => void;
  onViewDetails: (scenario: ScenarioRow) => void;
  onClose: () => void;
  onLayoutChange?: (slotOpen: boolean) => void;
}

/**
 * The right-hand detail drawer on `/catalog/scenarios`.
 *
 * Composed from `CatalogBrowseDrawerBody` like its peers; the content
 * decisions are which info rows (`scenarioInfoRows`, the details modal's) and
 * one action. It reads the selected scenario's details, so its hero is the
 * project graph with the scenario marked on it. Opening the project is the
 * primary action, the only thing to do with a scenario that is edited in its
 * project, and the way out comes last as on every drawer.
 */
export function ScenarioCatalogBrowseDrawer({
  scenario,
  onOpenProject,
  onViewDetails,
  onClose,
  onLayoutChange,
}: ScenarioCatalogBrowseDrawerProps) {
  const { details } = useScenarioDetails(scenario?.project.id, scenario?.id);
  // A stale answer for the card selected before must not mark this one.
  const current =
    details && scenario && details.id === scenario.id && details.project.id === scenario.project.id
      ? details
      : null;
  const edited = scenario ? catalogRelativeTime(scenario.project.updatedAt, "") : "";

  return (
    <CatalogBrowseDrawerShell presented={scenario != null} onLayoutChange={onLayoutChange}>
      {scenario ? (
        <CatalogBrowseDrawerBody
          kind="scenario"
          headerTitle="Scenario details"
          onClose={onClose}
          hero={
            <div className={styles.drawerKindHero} data-curio-scenario-thumbnail="true">
              <DataflowThumbnail
                preview={scenario.preview}
                highlight={current ? scenarioHighlight(current) : null}
              />
            </div>
          }
          title={scenario.name}
          badges={<ScenarioSwatch color={scenario.color} />}
          subtitle={<span className={styles.drawerPublisherText}>{scenario.project.name}</span>}
          metaLeft={scenarioNodeCount(scenario)}
          metaRight={edited ? `Edited ${edited}` : scenarioOriginLabel(scenario)}
          fresh={catalogIsFresh(scenario.project.updatedAt)}
          description={scenario.description}
          infoLabel="Scenario info"
          infoRows={scenarioInfoRows(scenario, current)}
          primaryAction={
            <button
              className={styles.addToPaletteBtn}
              type="button"
              title={`Open ${scenario.project.name}, where this scenario is edited`}
              onClick={() => onOpenProject(scenario)}
            >
              Open source project
            </button>
          }
          secondaryAction={
            <button
              className={styles.drawerLinkButton}
              type="button"
              onClick={() => onViewDetails(scenario)}
            >
              View details
            </button>
          }
        />
      ) : null}
    </CatalogBrowseDrawerShell>
  );
}

export default ScenarioCatalogBrowseDrawer;
