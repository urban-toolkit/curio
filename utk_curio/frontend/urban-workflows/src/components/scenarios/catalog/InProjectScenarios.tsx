import React, { useEffect, useMemo, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faClone,
  faPen,
  faPlay,
  faPlus,
  faTrashCan,
  type IconDefinition,
} from "@fortawesome/free-solid-svg-icons";

import { useSharedView } from "../../../hook/useSharedView";
import { useFlowContext } from "../../../providers/FlowProvider";
import type { ScenarioSortMode } from "../../../services/scenarioCatalog";
import type { Scenario } from "../../../utils/scenarios/scenarioModel";
import { scenarioNameProblem, setNameProblem } from "../../../utils/scenarios/scenarioEdits";
import { scenarioParts, type ScenarioParts } from "../../../utils/scenarios/scenarioParts";
import { useScenarioUi } from "../scenarioUi";
import { useScenarioActions } from "../useScenarioActions";
import { ScenarioCard } from "./ScenarioCard";
import { ScenarioDetailModal } from "./ScenarioDetailModal";
import { ScenarioSetGroup } from "./ScenarioSetGroup";
import { inProjectDetails, inProjectRow, liveGraphPreview, type LiveProject } from "./inProjectRows";
import shell from "../../packages/publishing/CatalogDrawerShell.module.css";
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
 * read off the canvas, so an unsaved one is listed too, inside a panel per
 * scenario set. On top, Define scenario; on each card, Run scenario, Edit
 * scenario (Define scenario on it), Duplicate scenario and Delete; in its details, its name, color and description. Pointing at a card marks the scenario's fixed context on the
 * canvas. A shared viewer reads them and changes nothing.
 */
export function InProjectScenarios({ scenarios, search, sort, presented }: InProjectScenariosProps) {
  const { nodes, edges, projectId, notebookOn, workflowNameRef, scenarioSets } = useFlowContext();
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

  // Under a heading per set, in the dataflow's order of sets; a scenario in no
  // set yet (made before its first save) under its own.
  const groups = useMemo(() => {
    const sets = scenarioSets ?? [];
    const known = new Set(sets.map((x) => x.id));
    const out = sets
      .map((set) => ({ id: set.id, name: set.name, items: shown.filter(({ scenario }) => scenario.set === set.id) }))
      .filter((g) => g.items.length > 0);
    const loose = shown.filter(({ scenario }) => !scenario.set || !known.has(scenario.set));
    if (loose.length > 0) out.push({ id: "", name: "Not in a set yet", items: loose });
    return out;
  }, [scenarioSets, shown]);

  const detail = cards.find(({ scenario }) => scenario.id === detailId) ?? null;

  const remove = (id: string) => {
    setHighlighted(null);
    actions.remove(id);
  };

  return (
    <>
      {!shared ? (
        <div className={styles.inProjectActions}>
          <ToolButton icon={faPlus} label="Define scenario" primary onClick={actions.saveSelectionAsScenario} />
        </div>
      ) : null}

      {scenarios.length === 0 ? (
        <div className={shell.empty}>
          This dataflow has no scenarios yet. Click Define scenario, then select the nodes the scenario changes.
          Duplicate a scenario to compare two versions.
        </div>
      ) : shown.length === 0 ? (
        <div className={shell.empty}>No scenarios match the current search.</div>
      ) : (
        groups.map((group) => (
          <ScenarioSetGroup
            key={group.id || "loose"}
            name={group.name}
            count={group.items.length}
            isSet={Boolean(group.id)}
            data={{ "data-scenario-set": group.id }}
            rename={
              group.id && !shared
                ? {
                    onRename: (name) => actions.renameSet(group.id, name),
                    problem: (name) => setNameProblem(scenarioSets ?? [], name, group.id),
                  }
                : undefined
            }
          >
            {group.items.map(({ scenario, parts }) => (
              <ScenarioCard
                key={scenario.id}
                scenario={inProjectRow(scenario, parts, project, preview)}
                testId={`scenario-card-${scenario.id}`}
                highlight={{
                  color: scenario.color,
                  members: parts.levers,
                  context: scenario.context ?? parts.context,
                  outcomes: scenario.outcomes ?? parts.outcomes,
                }}
                onOpenDetails={() => setDetailId(scenario.id)}
                onPoint={(on) => setHighlighted(on ? scenario.id : null)}
                corner={
                  shared ? undefined : (
                    <ToolButton icon={faTrashCan} label="Delete" danger onClick={() => remove(scenario.id)} />
                  )
                }
                controls={
                  shared ? undefined : (
                    <ScenarioControls
                      scenario={scenario}
                      parts={parts}
                      actions={actions}
                      notebookOn={notebookOn}
                    />
                  )
                }
              />
            ))}
          </ScenarioSetGroup>
        ))
      )}

      {detail ? (
        <ScenarioDetailModal
          key={detail.scenario.id}
          projectId={projectId ?? ""}
          scenarioId={detail.scenario.id}
          inProject={{
            details: inProjectDetails(detail.scenario, detail.parts, liveNodes, project, preview),
            onEdit: shared ? undefined : (patch) => actions.update(detail.scenario.id, patch),
            nameProblem: (name) =>
              scenarioNameProblem(scenarios, scenarioSets ?? [], detail.scenario.set, name, detail.scenario.id),
          }}
          onClose={() => setDetailId(null)}
        />
      ) : null}
    </>
  );
}

/** A small bordered button with an icon. *danger* (Delete) shows the icon
 *  alone, named by its tooltip and accessible name. */
function ToolButton({
  icon,
  label,
  onClick,
  disabled,
  primary,
  danger,
}: {
  icon: IconDefinition;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  danger?: boolean;
}) {
  const className = [styles.tool, primary ? styles.toolPrimary : "", danger ? styles.toolDanger : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      type="button"
      className={className}
      onClick={onClick}
      disabled={disabled}
      aria-label={danger ? label : undefined}
      data-tooltip={danger ? label : undefined}
    >
      <FontAwesomeIcon icon={icon} className={styles.toolIcon} aria-hidden />
      {danger ? null : label}
    </button>
  );
}

/** A card's buttons. A scenario with no node left can neither run nor be
 *  duplicated; it is collapsed and expanded on the canvas. Duplicate
 *  scenario copies its nodes into a new scenario of its set and opens the
 *  copy in Define scenario. Edit scenario opens Define scenario on it, where its nodes,
 *  shared context and outcomes, name and set are changed. */
function ScenarioControls({
  scenario,
  parts,
  actions,
  notebookOn,
}: {
  scenario: Scenario;
  parts: ScenarioParts;
  actions: ScenarioActions;
  notebookOn: boolean;
}) {
  const empty = parts.levers.length === 0;
  return (
    <>
      <ToolButton
        icon={faPlay}
        label="Run scenario"
        primary
        onClick={() => actions.runScenario(scenario.id)}
        disabled={empty}
      />
      <ToolButton icon={faPen} label="Edit scenario" onClick={() => actions.editScenario(scenario.id)} />
      {/* Duplicating adds nodes, which happens on the canvas only. */}
      <ToolButton
        icon={faClone}
        label="Duplicate scenario"
        onClick={() => actions.duplicateScenario(scenario.id)}
        disabled={empty || notebookOn}
      />
    </>
  );
}

export default InProjectScenarios;
