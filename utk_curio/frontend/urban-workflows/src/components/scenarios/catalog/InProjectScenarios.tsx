import React, { useEffect, useMemo, useState } from "react";

import { useSharedView } from "../../../hook/useSharedView";
import { useFlowContext } from "../../../providers/FlowProvider";
import type { ScenarioSortMode } from "../../../services/scenarioCatalog";
import type { Scenario } from "../../../utils/scenarios/scenarioModel";
import { scenarioParts, type ScenarioParts } from "../../../utils/scenarios/scenarioParts";
import { useScenarioUi } from "../scenarioUi";
import { useScenarioActions } from "../useScenarioActions";
import { ScenarioCard } from "./ScenarioCard";
import { ScenarioDetailModal } from "./ScenarioDetailModal";
import { inProjectDetails, inProjectRow, liveGraphPreview, type LiveProject } from "./inProjectRows";
import shell from "../../packages/publishing/CatalogDrawerShell.module.css";
import buttons from "../../packages/publishing/PackageCard.module.css";
import styles from "./ScenarioCatalogDrawer.module.css";

export interface InProjectScenariosProps {
  /** This dataflow's scenarios as the canvas holds them (`liveScenarios`). */
  scenarios: Scenario[];
  /** The drawer's search and sort. */
  search: string;
  sort: ScenarioSortMode;
  /** False while the drawer slides away. */
  presented: boolean;
}

type ScenarioActions = ReturnType<typeof useScenarioActions>;

/**
 * The Scenario Catalog drawer's In project tab: the open dataflow's scenarios,
 * read off the canvas, so an unsaved one is listed too. On top, Save selection
 * as scenario and Duplicate as scenario; on each card, Run scenario, Collapse
 * or Expand, Add selected and Remove selected (the canvas selection made
 * before the drawer opened) and Delete; in its details, its name, color and
 * description. Pointing at a card marks the scenario's fixed context on the
 * canvas. A shared viewer reads them and changes nothing.
 */
export function InProjectScenarios({ scenarios, search, sort, presented }: InProjectScenariosProps) {
  const { nodes, edges, projectId, notebookOn, workflowNameRef } = useFlowContext();
  const shared = useSharedView();
  const actions = useScenarioActions();
  const { setHighlighted } = useScenarioUi();
  const [detailId, setDetailId] = useState<string | null>(null);

  // A card that goes away under the pointer never sees it leave: the tab
  // changes, the drawer closes, the scenario is deleted. The canvas mark goes
  // with it.
  useEffect(() => () => setHighlighted(null), [setHighlighted]);
  useEffect(() => {
    if (!presented) setHighlighted(null);
  }, [presented, setHighlighted]);

  const liveNodes = nodes ?? [];
  const liveEdges = edges ?? [];
  const preview = useMemo(() => liveGraphPreview(liveNodes, liveEdges), [liveNodes, liveEdges]);
  const project: LiveProject = { id: projectId ?? null, name: workflowNameRef?.current ?? "" };
  const cards = useMemo(
    () => scenarios.map((scenario) => ({ scenario, parts: scenarioParts(scenario, liveNodes, liveEdges) })),
    [scenarios, liveNodes, liveEdges],
  );

  // The search and the sort the drawer's row sets, as Browse all reads them:
  // the name or the description; by name, or in the dataflow's own order.
  const query = search.trim().toLowerCase();
  const shown = useMemo(() => {
    const matching = query
      ? cards.filter(({ scenario }) => `${scenario.name} ${scenario.description ?? ""}`.toLowerCase().includes(query))
      : cards;
    return sort === "name"
      ? [...matching].sort((a, b) => a.scenario.name.localeCompare(b.scenario.name))
      : matching;
  }, [cards, query, sort]);

  const detail = cards.find(({ scenario }) => scenario.id === detailId) ?? null;

  const remove = (id: string) => {
    setHighlighted(null);
    actions.remove(id);
  };

  return (
    <>
      {!shared ? (
        <div className={styles.inProjectActions}>
          <button type="button" className={buttons.btnInstall} onClick={actions.saveSelectionAsScenario}>
            Save selection as scenario
          </button>
          {/* Duplicating adds nodes, which happens on the canvas only. */}
          <button
            type="button"
            className={buttons.btnInstall}
            onClick={() => actions.duplicate(true)}
            disabled={notebookOn}
          >
            Duplicate as scenario
          </button>
        </div>
      ) : null}

      {scenarios.length === 0 ? (
        <div className={shell.empty}>
          This dataflow has no scenarios yet. Select nodes (Shift and drag) and save them as a scenario, or
          duplicate them as one to compare two versions.
        </div>
      ) : shown.length === 0 ? (
        <div className={shell.empty}>No scenarios match the current search.</div>
      ) : (
        <div className={shell.cardList}>
          {shown.map(({ scenario, parts }) => (
            <ScenarioCard
              key={scenario.id}
              scenario={inProjectRow(scenario, parts, project, preview)}
              testId={`scenario-card-${scenario.id}`}
              highlight={{ color: scenario.color, members: parts.levers, context: parts.context }}
              onOpenDetails={() => setDetailId(scenario.id)}
              onPoint={(on) => setHighlighted(on ? scenario.id : null)}
              controls={
                shared ? undefined : (
                  <ScenarioControls scenario={scenario} parts={parts} actions={actions} onDelete={remove} />
                )
              }
            />
          ))}
        </div>
      )}

      {detail ? (
        <ScenarioDetailModal
          key={detail.scenario.id}
          projectId={projectId ?? ""}
          scenarioId={detail.scenario.id}
          inProject={{
            details: inProjectDetails(detail.scenario, detail.parts, liveNodes, project, preview),
            onEdit: shared ? undefined : (patch) => actions.update(detail.scenario.id, patch),
          }}
          onClose={() => setDetailId(null)}
        />
      ) : null}
    </>
  );
}

/** A card's buttons. A scenario with no node left can neither run nor
 *  collapse. */
function ScenarioControls({
  scenario,
  parts,
  actions,
  onDelete,
}: {
  scenario: Scenario;
  parts: ScenarioParts;
  actions: ScenarioActions;
  onDelete: (id: string) => void;
}) {
  const empty = parts.levers.length === 0;
  return (
    <>
      <button
        type="button"
        className={buttons.btnInstall}
        onClick={() => actions.runScenario(scenario.id)}
        disabled={empty}
      >
        Run scenario
      </button>
      <button
        type="button"
        className={buttons.btnInstall}
        onClick={() => actions.setCollapsed(scenario.id, !scenario.collapsed)}
        disabled={empty}
      >
        {scenario.collapsed ? "Expand" : "Collapse"}
      </button>
      <button type="button" className={buttons.btnInstall} onClick={() => actions.addSelected(scenario.id)}>
        Add selected
      </button>
      <button type="button" className={buttons.btnSecondary} onClick={() => actions.removeSelected(scenario.id)}>
        Remove selected
      </button>
      <button type="button" className={buttons.btnSecondary} onClick={() => onDelete(scenario.id)}>
        Delete
      </button>
    </>
  );
}

export default InProjectScenarios;
