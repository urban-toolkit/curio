import React, { useEffect, useMemo, useState } from "react";
import { useStore, type ReactFlowState } from "reactflow";
import { v4 as uuid } from "uuid";

import { useFlowContext } from "../../../providers/FlowProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import type { Scenario, ScenarioSet } from "../../../utils/scenarios/scenarioModel";
import { nextScenarioColor, nextScenarioName, scenarioNameProblem } from "../../../utils/scenarios/scenarioEdits";
import { inferContextOutcomes } from "../../../utils/scenarios/scenarioSets";
import { nodeLabel } from "../scenarioLabels";
import { useScenarioUi, type ScenarioDefine } from "../scenarioUi";
import styles from "./ScenarioDefinePanel.module.css";

const STEPS = ["Scenario-specific nodes", "Shared context & outcomes", "Name & set"];

type SetChoice = { kind: "new"; name: string } | { kind: "existing"; setId: string };
type Shared = "context" | "outcomes";
/** A list the panel edits: the scenario's own nodes, or a shared one. */
type Part = "nodes" | Shared;

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
 * 1. Scenario-specific nodes: the person selects on the canvas the nodes unique to the
 *    scenario and adds them (the canvas selection when the panel opened is
 *    there already), or removes one with ×, as in step 2.
 * 2. Shared context & outcomes: Curio infers the shared context (every node upstream
 *    of them) and the outcomes (every node downstream), which the canvas
 *    marks; the person confirms them, removes some, or adds selected nodes.
 * 3. Name & set: the scenario is named, given a color, and put in one of this dataflow's
 *    scenario sets, or in a new one. Save scenario writes it; nothing is
 *    written before.
 *
 * Opened on a saved scenario (Edit scenario, "edit"), it is the same three
 * steps, starting from what the scenario keeps: its nodes, its context and
 * outcomes, its name, color and set. Its Save changes
 * the scenario in place, from step 2 on.
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

  // The canvas selection, which "+ Add selected node" adds; nodes in another
  // scenario are left out.
  const selectedKey = useStore(selectedOf);
  const selection = useMemo(
    () => (selectedKey ? selectedKey.split("\n") : []).filter((id) => !boxedByOthers.has(id)),
    [selectedKey, boxedByOthers],
  );

  const [step, setStep] = useState<number>(define.mode === "edit" ? define.step ?? 1 : 1);
  const [members, setMembers] = useState<string[]>(() =>
    editing ? editing.nodes : define.mode === "new" ? define.nodes ?? [] : [],
  );
  const nodeIds = useMemo(() => nodes.map((n) => n.id), [nodes]);
  const boxed = useMemo(() => new Set([...boxedByOthers, ...members]), [boxedByOthers, members]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const labelOf = (id: string) => nodeLabel(byId.get(id), id);

  const [lists, setLists] = useState<Record<Shared, string[]> | null>(() =>
    editing ? { context: editing.context ?? [], outcomes: editing.outcomes ?? [] } : null,
  );
  // The nodes the shared lists were found from: other nodes find them anew.
  const [listsFor, setListsFor] = useState(() => (editing ? editing.nodes.join() : ""));
  const [color, setColor] = useState(() => editing?.color ?? nextScenarioColor(scenarios));
  const [name, setName] = useState(() => editing?.name ?? nextScenarioName(scenarios));
  const [choice, setChoice] = useState<SetChoice>(() =>
    editing?.set && scenarioSets.some((x) => x.id === editing.set)
      ? { kind: "existing", setId: editing.set }
      : scenarioSets.length > 0
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
    setListsFor(ids.join());
  };
  const toReview = () => {
    if (members.length === 0) {
      showToast("Add the nodes unique to this scenario first.", "warning");
      return;
    }
    // Other nodes are inferred anew; going back and on keeps the edits.
    if (!lists || members.join() !== listsFor) infer(members);
    setStep(2);
  };

  const rowsOf = (part: Part) => (part === "nodes" ? members : lists?.[part] ?? []);
  const remove = (part: Part, id: string) => {
    if (part === "nodes") setMembers((now) => now.filter((n) => n !== id));
    else setLists((now) => (now ? { ...now, [part]: now[part].filter((n) => n !== id) } : now));
  };
  // In the dataflow's order.
  const addSelected = (part: Part) => {
    const picked = selection.filter((id) => !boxed.has(id));
    if (picked.length === 0) {
      showToast("Select a node outside every scenario on the canvas first.", "warning");
      return;
    }
    const merged = (now: string[]) => {
      const keep = new Set([...now, ...picked]);
      return nodeIds.filter((id) => keep.has(id));
    };
    if (part === "nodes") setMembers(merged);
    else setLists((now) => (now ? { ...now, [part]: merged(now[part]) } : now));
  };

  const setId = choice.kind === "existing" ? choice.setId : null;
  const others = scenarios.filter((s) => setId && s.set === setId && s.id !== editing?.id);
  const inSet = (part: Shared) => new Set(others.flatMap((s) => s[part] ?? []));

  // No two scenarios of a set share a name; a new set has none yet.
  const nameProblem = scenarioNameProblem(scenarios, scenarioSets, setId, name, editing?.id);

  const save = () => {
    if (!lists) return;
    const scenarioName = name.trim();
    if (!scenarioName) {
      showToast("Give the scenario a name.", "warning");
      return;
    }
    if (nameProblem) {
      showToast(nameProblem, "warning");
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
    if (editing) {
      const next = scenarios.map((s) =>
        s.id === editing.id
          ? { ...s, name: scenarioName, color, nodes: [...members], set: target, context: lists.context, outcomes: lists.outcomes }
          : s,
      );
      // A set its last scenario left goes with it.
      const left = editing.set && editing.set !== target && !next.some((s) => s.set === editing.set);
      setScenarios(next, left ? sets.filter((x) => x.id !== editing.set) : sets);
      showToast(`Saved "${scenarioName}".`, "success");
      close();
      return;
    }
    const scenario: Scenario = {
      id: uuid(),
      name: scenarioName,
      color,
      nodes: [...members],
      set: target,
      context: lists.context,
      outcomes: lists.outcomes,
    };
    setScenarios([...scenarios, scenario], sets);
    showToast(`Saved "${scenarioName}" in the scenario set "${sets.find((s) => s.id === target)?.name}".`, "success");
    close();
  };

  const nodeRows = (ids: string[], part: Part) => (
    <ul className={styles.rows}>
      {ids.map((id) => (
        <li key={id} className={styles.row} data-node={id}>
          <span className={styles.rowLabel}>{labelOf(id)}</span>
          <button type="button" className={styles.remove} aria-label={`Remove ${labelOf(id)}`} onClick={() => remove(part, id)}>
            ×
          </button>
        </li>
      ))}
    </ul>
  );

  // The three lists look and work alike: rows with ×, then + Add selected node.
  const list = (part: Part, title: string, hint: string) => {
    const rows = rowsOf(part);
    const already = part === "nodes" ? null : inSet(part);
    const groups =
      already && setId && others.length > 0
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

  return (
    <aside className={styles.panel} role="dialog" aria-label="Define scenario" data-testid="scenario-define-panel">
      <header className={styles.header}>
        <div className={styles.title}>{editing ? `Edit scenario: ${editing.name}` : "Define scenario"}</div>
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
        {step === 1 &&
          list(
            "nodes",
            "Scenario-specific nodes",
            "The nodes this scenario changes. Select them on the canvas and add them.",
          )}

        {step === 2 && (
          <>
            <p className={styles.lead}>
              {editing ? "The scenario's shared context and outcomes, for its " : "Curio followed the links from "}
              <b>
                {members.length} scenario node{members.length === 1 ? "" : "s"}
              </b>
              . Check {editing ? "them" : "what it found"}: remove what is not part of the comparison, or select a node
              on the canvas and add it.
            </p>
            {list("context", "Shared context", "The nodes upstream it reads, the same in every scenario.")}
            {list("outcomes", "Shared outcomes", "The nodes downstream the scenarios are compared on.")}
            <button type="button" className={styles.link} onClick={() => infer(members)}>
              Start again from what Curio found
            </button>
          </>
        )}

        {step === 3 && (
          <>
            <label className={styles.field}>
              Scenario name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                data-testid="scenario-define-name"
                aria-invalid={nameProblem ? true : undefined}
                aria-describedby={nameProblem ? "scenario-define-name-problem" : undefined}
              />
              {nameProblem && (
                <span className={styles.problem} id="scenario-define-name-problem" role="alert">
                  {nameProblem}
                </span>
              )}
            </label>
            <label className={`${styles.field} ${styles.colorField}`}>
              Color
              <input
                type="color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                data-testid="scenario-define-color"
              />
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
        {step > 1 && (
          <button type="button" className={styles.secondary} onClick={() => setStep(step - 1)}>
            Back
          </button>
        )}
        {step === 1 && (
          <button type="button" className={styles.primary} onClick={toReview} disabled={members.length === 0}>
            Next: shared context & outcomes
          </button>
        )}
        {step === 2 && (
          <button type="button" className={editing ? styles.secondary : styles.primary} onClick={() => setStep(3)}>
            Next: name & set
          </button>
        )}
        {(step === 3 || (editing && step === 2)) && (
          <button
            type="button"
            className={styles.primary}
            onClick={save}
            disabled={!!nameProblem}
            data-testid="scenario-define-save"
          >
            {editing ? "Save" : "Save scenario"}
          </button>
        )}
      </footer>
    </aside>
  );
}
