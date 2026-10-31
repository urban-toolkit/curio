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
  /** In Browse all: whether the card is selected, what a click on it does
   *  (*toggle* with Ctrl or Cmd held), and its drag, which brings the
   *  selected scenarios. */
  selected?: boolean;
  onSelect?: (toggle: boolean) => void;
  onDragStart?: (event: React.DragEvent<HTMLElement>) => void;
  onDragEnd?: () => void;
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
 * nodes the scenario holds shows in the details, which load them. In Browse
 * all a click selects the card (Ctrl or Cmd adds one of its set), and the card
 * is the drag source of the selected scenarios, which arrive on the canvas as
 * copies and change nothing in their project. In the In project tab the scenario is
 * this dataflow's: the card marks its nodes on the graph and carries its
 * buttons.
 */
export const ScenarioCard: React.FC<ScenarioCardProps> = ({
  scenario,
  onOpenDetails,
  controls,
  corner,
  selected = false,
  onSelect,
  onDragStart,
  onDragEnd,
  onPoint,
  highlight = null,
  testId,
}) => {
  const detailsLabel = `View ${scenario.name} (${scenario.project.name}) details`;
  // A click on the card's own body selects it; its thumbnail, View details and
  // any other control keep their own click.
  const select = onSelect
    ? (event: React.MouseEvent<HTMLElement>) => {
        if ((event.target as HTMLElement).closest("button, a, input, select, textarea")) return;
        onSelect(event.ctrlKey || event.metaKey);
      }
    : undefined;
  const selectByKey = onSelect
    ? (event: React.KeyboardEvent<HTMLElement>) => {
        if (event.target !== event.currentTarget || (event.key !== " " && event.key !== "Enter")) return;
        event.preventDefault();
        onSelect(event.ctrlKey || event.metaKey);
      }
    : undefined;

  return (
    <article
      className={selected ? `${styles.card} ${local.cardSelected}` : styles.card}
      /* Same attribute the browse cards carry, so a scenario shares one
         identifier across surfaces. */
      data-scenario-key={scenario.key}
      data-testid={testId}
      draggable={onDragStart ? true : undefined}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={select}
      onKeyDown={selectByKey}
      role={onSelect ? "option" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-selected={onSelect ? selected : undefined}
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
