import React, { useEffect, useMemo, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faXmark } from "@fortawesome/free-solid-svg-icons";

import { useFlowContext } from "../../providers/FlowProvider";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import { scenarioParts } from "../../utils/scenarios/scenarioParts";
import { nodeLabel } from "./scenarioLabels";
import { useScenarioUi } from "./scenarioUi";
import { useScenarioActions } from "./useScenarioActions";
import styles from "./ScenariosPanel.module.css";

/**
 * The Scenarios panel (#662), docked on the right of the canvas: each
 * scenario's name, color and description, its fixed context, levers and
 * outcomes, and what can be done to it. Pointing at a scenario marks its fixed
 * context on the canvas.
 */
export function ScenariosPanel() {
  const { scenarios, notebookOn } = useFlowContext();
  const { panelOpen, setPanelOpen, setHighlighted } = useScenarioUi();
  const actions = useScenarioActions();

  // A closed panel highlights nothing.
  useEffect(() => {
    if (!panelOpen) setHighlighted(null);
  }, [panelOpen, setHighlighted]);

  if (!panelOpen) return null;

  return (
    <aside className={styles.panel} aria-label="Scenarios" data-testid="scenarios-panel">
      <header className={styles.header}>
        <h2 className={styles.title}>Scenarios</h2>
        <button
          type="button"
          className={styles.close}
          aria-label="Close the Scenarios panel"
          onClick={() => setPanelOpen(false)}
        >
          <FontAwesomeIcon icon={faXmark} />
        </button>
      </header>
      <div className={styles.actions}>
        <button type="button" className={styles.action} onClick={actions.saveSelectionAsScenario}>
          Save selection as scenario
        </button>
        {/* Duplicating adds nodes, which happens on the canvas only. */}
        <button
          type="button"
          className={styles.action}
          onClick={() => actions.duplicate(true)}
          disabled={notebookOn}
        >
          Duplicate as scenario
        </button>
      </div>
      {scenarios.length === 0 ? (
        <p className={styles.empty}>
          No scenarios yet. Select nodes (Shift and drag) and save them as a scenario, or duplicate
          them as one to compare two versions.
        </p>
      ) : (
        <ul className={styles.list}>
          {scenarios.map((scenario) => (
            <ScenarioCard
              key={scenario.id}
              scenario={scenario}
              actions={actions}
              onPoint={(on) => setHighlighted(on ? scenario.id : null)}
            />
          ))}
        </ul>
      )}
    </aside>
  );
}

function ScenarioCard({
  scenario,
  actions,
  onPoint,
}: {
  scenario: Scenario;
  actions: ReturnType<typeof useScenarioActions>;
  onPoint: (on: boolean) => void;
}) {
  const { nodes, edges } = useFlowContext();
  const [name, setName] = useState(scenario.name);
  const [description, setDescription] = useState(scenario.description ?? "");
  useEffect(() => setName(scenario.name), [scenario.name]);
  useEffect(() => setDescription(scenario.description ?? ""), [scenario.description]);

  const parts = useMemo(() => scenarioParts(scenario, nodes, edges), [scenario, nodes, edges]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const names = (ids: string[]) => ids.map((id) => nodeLabel(byId.get(id), id));

  const commitName = () => {
    if (name.trim() && name.trim() !== scenario.name) actions.update(scenario.id, { name });
    else setName(scenario.name);
  };
  const commitDescription = () => {
    if (description !== (scenario.description ?? "")) actions.update(scenario.id, { description });
  };

  return (
    <li
      className={styles.card}
      style={{ borderLeftColor: scenario.color }}
      data-testid={`scenario-card-${scenario.id}`}
      onMouseEnter={() => onPoint(true)}
      onMouseLeave={() => onPoint(false)}
    >
      <div className={styles.nameRow}>
        <input
          type="color"
          className={styles.color}
          aria-label={`Color of ${scenario.name}`}
          value={scenario.color}
          onChange={(e) => actions.update(scenario.id, { color: e.target.value })}
        />
        <input
          type="text"
          className={styles.name}
          aria-label="Scenario name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={commitName}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
        />
      </div>
      <textarea
        className={styles.description}
        aria-label="Scenario description"
        placeholder="Description"
        rows={2}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onBlur={commitDescription}
      />
      <Part
        title="Fixed context"
        names={names(parts.context)}
        empty={parts.levers.length === 0 ? "-" : "None: everything it reads is in it."}
        testId="context"
      />
      <Part title="Levers" names={names(parts.levers)} empty="No nodes: add some, or delete it." testId="levers" />
      <Part title="Outcomes" names={names(parts.outcomes)} empty="-" testId="outcomes" />
      <div className={styles.buttons}>
        <button type="button" onClick={() => actions.runScenario(scenario.id)} disabled={parts.levers.length === 0}>
          Run scenario
        </button>
        <button
          type="button"
          onClick={() => actions.setCollapsed(scenario.id, !scenario.collapsed)}
          disabled={parts.levers.length === 0}
        >
          {scenario.collapsed ? "Expand" : "Collapse"}
        </button>
        <button type="button" onClick={() => actions.addSelected(scenario.id)}>
          Add selected
        </button>
        <button type="button" onClick={() => actions.removeSelected(scenario.id)}>
          Remove selected
        </button>
        <button type="button" className={styles.danger} onClick={() => actions.remove(scenario.id)}>
          Delete
        </button>
      </div>
    </li>
  );
}

function Part({ title, names, empty, testId }: { title: string; names: string[]; empty: string; testId: string }) {
  return (
    <div className={styles.part} data-scenario-part={testId}>
      <div className={styles.partTitle}>{title}</div>
      {names.length === 0 ? (
        <div className={styles.partEmpty}>{empty}</div>
      ) : (
        <ul className={styles.partList}>
          {names.map((n, i) => (
            <li key={`${n}-${i}`}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
