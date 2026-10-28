import React, { useEffect, useMemo, useState } from "react";
import { v4 as uuid } from "uuid";

import { useFlowContext } from "../../../providers/FlowProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import type { Scenario, ScenarioSet } from "../../../utils/scenarios/scenarioModel";
import { nextScenarioColor, nextScenarioName } from "../../../utils/scenarios/scenarioEdits";
import { inferContextOutcomes } from "../../../utils/scenarios/scenarioSets";
import { nodeLabel } from "../scenarioLabels";
import { useScenarioUi, type ScenarioDefine } from "../scenarioUi";
import styles from "./ScenarioDefinePanel.module.css";

const STEPS = ["Select nodes", "Choose a set", "Review context & outcomes", "Save"];

type SetChoice = { kind: "new"; name: string } | { kind: "existing"; setId: string };
type Part = "context" | "outcomes";

/** A set id no set of *sets* has. */
function freshSetId(sets: readonly ScenarioSet[]): string {
  const taken = new Set(sets.map((s) => s.id));
  let id = `set-${uuid()}`;
  while (taken.has(id)) id = `set-${uuid()}`;
  return id;
}

/**
 * The define panel: how a scenario is made and how its context and outcomes
 * are finalized. The nodes unique to the scenario are selected first (step 1,
 * before the panel opens); then the scenario goes in a new set or an existing
 * one of this dataflow (2); then Curio proposes its shared context (every node
 * upstream of it) and its outcomes (every node downstream), which the person
 * edits (3); Save writes it (4). Nothing changes until Save.
 *
 * Opened on a scenario already made ("edit"), it starts at step 3 with the
 * lists the scenario keeps. While it is open the canvas marks the lists.
 */
export function ScenarioDefinePanel({ define }: { define: ScenarioDefine }) {
  const { scenarios, scenarioSets, nodes, edges, setScenarios, workflowNameRef } = useFlowContext();
  const { setDefine, setPreview } = useScenarioUi();
  const { showToast } = useToastContext();

  const editing = define.mode === "edit" ? scenarios.find((s) => s.id === define.scenarioId) : undefined;
  const members = useMemo(
    () => (define.mode === "edit" ? editing?.nodes ?? [] : define.nodes),
    [define, editing],
  );
  const nodeIds = useMemo(() => nodes.map((n) => n.id), [nodes]);
  const boxed = useMemo(
    () => new Set([...scenarios.flatMap((s) => s.nodes), ...members]),
    [scenarios, members],
  );
  const inferred = useMemo(
    () => inferContextOutcomes(members, nodeIds, edges, boxed),
    [members, nodeIds, edges, boxed],
  );
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const labelOf = (id: string) => nodeLabel(byId.get(id), id);

  const [step, setStep] = useState(define.mode === "edit" ? 3 : 2);
  const [name, setName] = useState(() => editing?.name ?? nextScenarioName(scenarios));
  const [choice, setChoice] = useState<SetChoice>(() =>
    scenarioSets.length > 0
      ? { kind: "existing", setId: scenarioSets[0].id }
      : { kind: "new", name: workflowNameRef?.current?.trim() || "Scenario set" },
  );
  const [lists, setLists] = useState<Record<Part, string[]>>(() => ({
    context: editing?.context ?? inferred.context,
    outcomes: editing?.outcomes ?? inferred.outcomes,
  }));

  // The canvas marks what the panel holds, until it closes.
  useEffect(() => {
    setPreview({ context: lists.context, outcomes: lists.outcomes });
  }, [lists, setPreview]);
  useEffect(() => () => setPreview(null), [setPreview]);

  const close = () => setDefine(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDefine(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setDefine]);

  const setId = editing?.set ?? (choice.kind === "existing" ? choice.setId : null);
  const set = scenarioSets.find((s) => s.id === setId);
  const others = scenarios.filter((s) => setId && s.set === setId && s.id !== editing?.id);
  const inSet = (part: Part) => new Set(others.flatMap((s) => s[part] ?? []));

  const remove = (part: Part, id: string) =>
    setLists((now) => ({ ...now, [part]: now[part].filter((n) => n !== id) }));
  const addSelected = (part: Part) => {
    const picked = nodes.filter((n) => n.selected && !boxed.has(n.id)).map((n) => n.id);
    if (picked.length === 0) {
      showToast("Select a node outside every scenario on the canvas first.", "warning");
      return;
    }
    setLists((now) => {
      const keep = new Set([...now[part], ...picked]);
      return { ...now, [part]: nodeIds.filter((id) => keep.has(id)) };
    });
  };
  const reset = () => setLists({ context: inferred.context, outcomes: inferred.outcomes });

  const save = () => {
    if (editing) {
      setScenarios(
        scenarios.map((s) => (s.id === editing.id ? { ...s, context: lists.context, outcomes: lists.outcomes } : s)),
      );
      showToast(`Saved the context and outcomes of "${editing.name}".`, "success");
      close();
      return;
    }
    const scenarioName = name.trim();
    if (!scenarioName) {
      showToast("Give the scenario a name.", "warning");
      return;
    }
    let sets = scenarioSets;
    let target: string;
    if (choice.kind === "new") {
      const setName = choice.name.trim();
      if (!setName) {
        showToast("Give the new set a name.", "warning");
        return;
      }
      target = freshSetId(scenarioSets);
      sets = [...scenarioSets, { id: target, name: setName }];
    } else {
      target = choice.setId;
    }
    const scenario: Scenario = {
      id: uuid(),
      name: scenarioName,
      color: nextScenarioColor(scenarios),
      nodes: [...members],
      set: target,
      context: lists.context,
      outcomes: lists.outcomes,
    };
    setScenarios([...scenarios, scenario], sets);
    showToast(`Saved "${scenarioName}" in "${sets.find((s) => s.id === target)?.name}".`, "success");
    close();
  };

  const list = (part: Part, title: string, hint: string) => {
    const already = inSet(part);
    const rows = lists[part];
    const groups = setId && others.length > 0
      ? [
          { label: "Already in the set", ids: rows.filter((id) => already.has(id)) },
          { label: "New to the set", ids: rows.filter((id) => !already.has(id)) },
        ]
      : [{ label: null, ids: rows }];
    return (
      <section className={styles.part} aria-label={title} data-testid={`scenario-define-${part}`}>
        <h3 className={styles.partTitle}>{title}</h3>
        <p className={styles.hint}>{hint}</p>
        {rows.length === 0 && <p className={styles.empty}>None</p>}
        {groups.map(
          (g) =>
            g.ids.length > 0 && (
              <div key={g.label ?? "all"} className={styles.group}>
                {g.label && <div className={styles.groupLabel}>{g.label}</div>}
                <ul className={styles.rows}>
                  {g.ids.map((id) => (
                    <li key={id} className={styles.row} data-node={id}>
                      <span className={styles.rowLabel}>{labelOf(id)}</span>
                      <button
                        type="button"
                        className={styles.remove}
                        aria-label={`Remove ${labelOf(id)}`}
                        onClick={() => remove(part, id)}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ),
        )}
        <button type="button" className={styles.secondary} onClick={() => addSelected(part)}>
          + Add selected node
        </button>
      </section>
    );
  };

  const who = editing?.name ?? (name.trim() || "a new scenario");
  return (
    <aside className={styles.panel} role="dialog" aria-label="Define a scenario" data-testid="scenario-define-panel">
      <header className={styles.header}>
        <div className={styles.title}>{editing ? "Edit context & outcomes" : "Define a scenario"}</div>
        <button type="button" className={styles.close} aria-label="Close" onClick={close}>
          ×
        </button>
      </header>
      <ol className={styles.steps} aria-label="Steps">
        {STEPS.map((label, index) => {
          const n = index + 1;
          const state = n < step ? "done" : n === step ? "current" : "todo";
          return (
            <li key={label} className={styles.step} data-state={state} aria-current={state === "current" ? "step" : undefined}>
              <span className={styles.stepMark}>{state === "done" ? "✓" : n}</span>
              {label}
            </li>
          );
        })}
      </ol>
      <div className={styles.body}>
        <p className={styles.lead}>
          {members.length} node{members.length === 1 ? "" : "s"} of <b>{who}</b>, unique to it.
        </p>

        {step === 2 && (
          <>
            <label className={styles.field}>
              Scenario name
              <input value={name} onChange={(e) => setName(e.target.value)} data-testid="scenario-define-name" />
            </label>
            <fieldset className={styles.choices}>
              <legend className={styles.partTitle}>Put it in a set</legend>
              <p className={styles.hint}>
                Scenarios of one set are compared on the same context and outcomes; scenarios of different sets never
                mix.
              </p>
              {scenarioSets.map((s) => {
                const its = scenarios.filter((x) => x.set === s.id);
                const on = choice.kind === "existing" && choice.setId === s.id;
                return (
                  <label key={s.id} className={styles.choice} data-on={on}>
                    <input type="radio" name="scenario-set" checked={on} onChange={() => setChoice({ kind: "existing", setId: s.id })} />
                    <span className={styles.choiceText}>
                      <b>{s.name}</b>
                      <span className={styles.dots}>
                        {its.map((x) => (
                          <span key={x.id} className={styles.dot} style={{ background: x.color }} data-tooltip={x.name} />
                        ))}
                        {its.length} scenario{its.length === 1 ? "" : "s"}
                      </span>
                    </span>
                  </label>
                );
              })}
              <label className={styles.choice} data-on={choice.kind === "new"}>
                <input
                  type="radio"
                  name="scenario-set"
                  checked={choice.kind === "new"}
                  onChange={() => setChoice({ kind: "new", name: workflowNameRef?.current?.trim() || "Scenario set" })}
                />
                <span className={styles.choiceText}>
                  <b>A new set</b>
                  {choice.kind === "new" && (
                    <input
                      aria-label="Set name"
                      value={choice.name}
                      onChange={(e) => setChoice({ kind: "new", name: e.target.value })}
                      data-testid="scenario-define-set-name"
                    />
                  )}
                </span>
              </label>
            </fieldset>
          </>
        )}

        {step === 3 && (
          <>
            {set && (
              <p className={styles.hint}>
                In <b>{set.name}</b>
                {others.length > 0 ? ` with ${others.map((s) => s.name).join(", ")}` : ""}.
              </p>
            )}
            {list("context", "Shared context", "The nodes upstream of it that it uses.")}
            {list("outcomes", "Outcomes", "The nodes downstream of it that it feeds.")}
            <button type="button" className={styles.link} onClick={reset}>
              Start again from what Curio found
            </button>
          </>
        )}
      </div>
      <footer className={styles.footer}>
        <button type="button" className={styles.secondary} onClick={close}>
          Cancel
        </button>
        {step === 3 && !editing && (
          <button type="button" className={styles.secondary} onClick={() => setStep(2)}>
            Back
          </button>
        )}
        {step === 2 ? (
          <button type="button" className={styles.primary} onClick={() => setStep(3)}>
            Next: review context & outcomes
          </button>
        ) : (
          <button type="button" className={styles.primary} onClick={save} data-testid="scenario-define-save">
            {editing ? "Save" : "Save scenario"}
          </button>
        )}
      </footer>
    </aside>
  );
}
