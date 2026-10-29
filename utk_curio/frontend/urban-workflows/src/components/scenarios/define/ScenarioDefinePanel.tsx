import React, { useEffect, useMemo, useState } from "react";
import { useStore, type ReactFlowState } from "reactflow";
import { v4 as uuid } from "uuid";

import { useFlowContext } from "../../../providers/FlowProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import type { Scenario, ScenarioSet } from "../../../utils/scenarios/scenarioModel";
import { nextScenarioColor, nextScenarioName } from "../../../utils/scenarios/scenarioEdits";
import { inferContextOutcomes } from "../../../utils/scenarios/scenarioSets";
import { nodeLabel } from "../scenarioLabels";
import { useScenarioUi, type ScenarioDefine } from "../scenarioUi";
import styles from "./ScenarioDefinePanel.module.css";

const STEPS = ["Scenario nodes", "Context & outcomes", "Name & set"];

type SetChoice = { kind: "new"; name: string } | { kind: "existing"; setId: string };
type Part = "context" | "outcomes";

/** A set id no set of *sets* has. */
function freshSetId(sets: readonly ScenarioSet[]): string {
  const taken = new Set(sets.map((s) => s.id));
  let id = `set-${uuid()}`;
  while (taken.has(id)) id = `set-${uuid()}`;
  return id;
}

/** The ids of the nodes selected on the canvas, as React Flow holds them. */
const selectedOf = (s: ReactFlowState) =>
  Array.from(s.nodeInternals.values())
    .filter((n) => n.selected && !n.hidden)
    .map((n) => n.id)
    .join("\n");

/**
 * Define scenario, beside the canvas so the canvas stays usable:
 *
 * 1. Scenario nodes: the person selects on the canvas the nodes unique to the
 *    scenario; the panel lists them as they are selected.
 * 2. Context & outcomes: Curio infers the shared context (every node upstream
 *    of them) and the outcomes (every node downstream), which the canvas
 *    marks; the person confirms them, removes some, or adds selected nodes.
 * 3. Name & set: the scenario is named and put in one of this dataflow's
 *    scenario sets, or in a new one. Save scenario writes it; nothing is
 *    written before.
 *
 * Opened on a saved scenario ("edit"), it is step 2 alone, on the lists the
 * scenario keeps.
 */
export function ScenarioDefinePanel({ define }: { define: ScenarioDefine }) {
  const { scenarios, scenarioSets, nodes, edges, setScenarios, workflowNameRef } = useFlowContext();
  const { setDefine, setPreview } = useScenarioUi();
  const { showToast } = useToastContext();

  const editing = define.mode === "edit" ? scenarios.find((s) => s.id === define.scenarioId) : undefined;
  const boxedByOthers = useMemo(
    () => new Set(scenarios.filter((s) => s.id !== editing?.id).flatMap((s) => s.nodes)),
    [scenarios, editing],
  );

  // Step 1 reads the canvas selection live; nodes already in a scenario are left out.
  const selectedKey = useStore(selectedOf);
  const selection = useMemo(
    () => (selectedKey ? selectedKey.split("\n") : []).filter((id) => !boxedByOthers.has(id)),
    [selectedKey, boxedByOthers],
  );

  const [step, setStep] = useState(editing ? 2 : 1);
  const [members, setMembers] = useState<string[]>(() =>
    editing ? editing.nodes : define.mode === "new" ? define.nodes ?? [] : [],
  );
  const nodeIds = useMemo(() => nodes.map((n) => n.id), [nodes]);
  const boxed = useMemo(() => new Set([...boxedByOthers, ...members]), [boxedByOthers, members]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const labelOf = (id: string) => nodeLabel(byId.get(id), id);

  const [lists, setLists] = useState<Record<Part, string[]> | null>(() =>
    editing ? { context: editing.context ?? [], outcomes: editing.outcomes ?? [] } : null,
  );
  const [name, setName] = useState(() => nextScenarioName(scenarios));
  const [choice, setChoice] = useState<SetChoice>(() =>
    scenarioSets.length > 0
      ? { kind: "existing", setId: scenarioSets[0].id }
      : { kind: "new", name: workflowNameRef?.current?.trim() || "Scenario set" },
  );

  // While it is open the canvas marks the scenario's nodes' context and outcomes.
  useEffect(() => {
    setPreview(lists && step >= 2 ? { context: lists.context, outcomes: lists.outcomes } : null);
  }, [lists, step, setPreview]);
  useEffect(() => () => setPreview(null), [setPreview]);

  const close = () => setDefine(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDefine(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setDefine]);

  const infer = (ids: string[]) => {
    const found = inferContextOutcomes(ids, nodeIds, edges, new Set([...boxedByOthers, ...ids]));
    setLists({ context: found.context, outcomes: found.outcomes });
  };
  const toReview = () => {
    const ids = selection.length > 0 ? selection : members;
    if (ids.length === 0) {
      showToast("Select the nodes unique to this scenario on the canvas first.", "warning");
      return;
    }
    // A new selection is inferred anew; going back and on keeps the edits.
    if (!lists || ids.join() !== members.join()) infer(ids);
    setMembers(ids);
    setStep(2);
  };

  const remove = (part: Part, id: string) =>
    setLists((now) => (now ? { ...now, [part]: now[part].filter((n) => n !== id) } : now));
  const addSelected = (part: Part) => {
    const picked = selection.filter((id) => !boxed.has(id));
    if (picked.length === 0) {
      showToast("Select a node outside every scenario on the canvas first.", "warning");
      return;
    }
    setLists((now) => {
      if (!now) return now;
      const keep = new Set([...now[part], ...picked]);
      return { ...now, [part]: nodeIds.filter((id) => keep.has(id)) };
    });
  };

  const setId = editing?.set ?? (choice.kind === "existing" ? choice.setId : null);
  const others = scenarios.filter((s) => setId && s.set === setId && s.id !== editing?.id);
  const inSet = (part: Part) => new Set(others.flatMap((s) => s[part] ?? []));

  const save = () => {
    if (!lists) return;
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
        showToast("Give the new scenario set a name.", "warning");
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
    showToast(`Saved "${scenarioName}" in the scenario set "${sets.find((s) => s.id === target)?.name}".`, "success");
    close();
  };

  const nodeRows = (ids: string[], part?: Part) => (
    <ul className={styles.rows}>
      {ids.map((id) => (
        <li key={id} className={styles.row} data-node={id}>
          <span className={styles.rowLabel}>{labelOf(id)}</span>
          {part && (
            <button
              type="button"
              className={styles.remove}
              aria-label={`Remove ${labelOf(id)}`}
              onClick={() => remove(part, id)}
            >
              ×
            </button>
          )}
        </li>
      ))}
    </ul>
  );

  const list = (part: Part, title: string, hint: string) => {
    const rows = lists?.[part] ?? [];
    const already = inSet(part);
    const groups =
      setId && others.length > 0
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
                {nodeRows(g.ids, part)}
              </div>
            ),
        )}
        <button type="button" className={styles.secondary} onClick={() => addSelected(part)}>
          + Add selected node
        </button>
      </section>
    );
  };

  const steps = editing ? [STEPS[1]] : STEPS;
  const current = editing ? 1 : step;
  return (
    <aside className={styles.panel} role="dialog" aria-label="Define scenario" data-testid="scenario-define-panel">
      <header className={styles.header}>
        <div className={styles.title}>{editing ? `Context & outcomes of ${editing.name}` : "Define scenario"}</div>
        <button type="button" className={styles.close} aria-label="Close" onClick={close}>
          ×
        </button>
      </header>
      {!editing && (
        <ol className={styles.steps} aria-label="Steps">
          {steps.map((label, index) => {
            const n = index + 1;
            const state = n < current ? "done" : n === current ? "current" : "todo";
            return (
              <li key={label} className={styles.step} data-state={state} aria-current={state === "current" ? "step" : undefined}>
                <span className={styles.stepMark}>{state === "done" ? "✓" : n}</span>
                {label}
              </li>
            );
          })}
        </ol>
      )}
      <div className={styles.body}>
        {step === 1 && (
          <section className={styles.part} aria-label="Scenario nodes">
            <h3 className={styles.question}>Which nodes are unique to this scenario?</h3>
            <p className={styles.hint}>
              Select them on the canvas: click one, or hold Shift and drag a box around several. These are the nodes
              this scenario changes, such as a widget value, a line of code or an edited layer. Leave out the data
              they read and the views they feed: Curio finds those next.
            </p>
            {selection.length === 0 ? (
              <p className={styles.waiting} data-testid="scenario-define-waiting">
                Waiting for a selection on the canvas…
              </p>
            ) : (
              <>
                <div className={styles.groupLabel}>
                  {selection.length} node{selection.length === 1 ? "" : "s"} selected
                </div>
                {nodeRows(selection)}
              </>
            )}
          </section>
        )}

        {step === 2 && (
          <>
            {!editing && (
              <p className={styles.lead}>
                Curio followed the links from{" "}
                <b>
                  {members.length} scenario node{members.length === 1 ? "" : "s"}
                </b>
                . Check what it found: remove what is not part of the comparison, or select a node on the canvas and add
                it.
              </p>
            )}
            {list("context", "Shared context", "The nodes upstream that this scenario uses, held the same across scenarios.")}
            {list("outcomes", "Outcomes", "The nodes downstream that this scenario feeds: what the scenarios are compared on.")}
            {!editing && (
              <button type="button" className={styles.link} onClick={() => infer(members)}>
                Start again from what Curio found
              </button>
            )}
          </>
        )}

        {step === 3 && (
          <>
            <label className={styles.field}>
              Scenario name
              <input value={name} onChange={(e) => setName(e.target.value)} data-testid="scenario-define-name" />
            </label>
            <fieldset className={styles.choices}>
              <legend className={styles.question}>Which scenario set does it belong to?</legend>
              <p className={styles.hint}>
                A scenario set holds the scenarios that answer one question. They are compared on the same context and
                outcomes; scenarios of different sets never mix.
              </p>
              {scenarioSets.map((s) => {
                const its = scenarios.filter((x) => x.set === s.id);
                const on = choice.kind === "existing" && choice.setId === s.id;
                return (
                  <label key={s.id} className={styles.choice} data-on={on}>
                    <input
                      type="radio"
                      name="scenario-set"
                      checked={on}
                      onChange={() => setChoice({ kind: "existing", setId: s.id })}
                    />
                    <span className={styles.choiceText}>
                      <b>{s.name}</b>
                      <span className={styles.dots}>
                        {its.map((x) => (
                          <span key={x.id} className={styles.member}>
                            <span className={styles.dot} style={{ background: x.color }} />
                            {x.name}
                          </span>
                        ))}
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
                  <b>Create a new scenario set</b>
                  {choice.kind === "new" && (
                    <input
                      aria-label="New scenario set name"
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
      </div>
      <footer className={styles.footer}>
        <button type="button" className={styles.secondary} onClick={close}>
          Cancel
        </button>
        {!editing && step > 1 && (
          <button type="button" className={styles.secondary} onClick={() => setStep(step - 1)}>
            Back
          </button>
        )}
        {step === 1 && (
          <button type="button" className={styles.primary} onClick={toReview} disabled={selection.length === 0 && members.length === 0}>
            Next: context & outcomes
          </button>
        )}
        {step === 2 && !editing && (
          <button type="button" className={styles.primary} onClick={() => setStep(3)}>
            Next: name & set
          </button>
        )}
        {(step === 3 || editing) && (
          <button type="button" className={styles.primary} onClick={save} data-testid="scenario-define-save">
            {editing ? "Save" : "Save scenario"}
          </button>
        )}
      </footer>
    </aside>
  );
}
