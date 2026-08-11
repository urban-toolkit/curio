import React, { useState } from "react";
import type { AgentProposalPart } from "../../../api/agentsApi";
import styles from "./AgentReviewCard.module.css";

/** dev/67-5/67-8: the per-node review state (from the activeProposal mirror). */
export interface PlanNodeReviewState {
  appliedRefs: string[];
  editedGoals: Record<string, string>;
  /** dev/67-8: edge index → planned|applied|refused. */
  edgeStates?: Record<string, string>;
}

/** One planned node's review row (dev/67-5, Simulation Mode: create):
 * editable goal, expects line, per-node Apply → Created ✓. */
const PlanNodeRow: React.FC<{
  node: { ref: string; nodeType: string; title: string; intent: string; expects?: string };
  applied: boolean;
  goal: string;
  onApply: () => Promise<void>;
  onSaveGoal: (goal: string) => Promise<void>;
}> = ({ node, applied, goal, onApply, onSaveGoal }) => {
  const [draft, setDraft] = useState(goal);
  const [busy, setBusy] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);

  const saveGoal = async () => {
    const next = draft.trim();
    if (!next || next === goal.trim()) return;
    setRowError(null);
    try {
      await onSaveGoal(next);
    } catch (e) {
      setRowError(e instanceof Error ? e.message : "The goal edit failed");
    }
  };

  const apply = async () => {
    if (busy || applied) return;
    setBusy(true);
    setRowError(null);
    try {
      await onApply();
    } catch (e) {
      setRowError(e instanceof Error ? e.message : "Creating the node failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className={styles.planNodeRow}>
      <div className={styles.planNodeHead}>
        <span className={styles.planNodeTitle}>{node.title}</span>
        <span className={styles.planNodeType}>{node.nodeType}</span>
        {applied ? (
          <span className={styles.planNodeCreated}>Created ✓</span>
        ) : (
          <button
            type="button"
            className={styles.apply}
            disabled={busy}
            onClick={() => void apply()}
            aria-label={`Create node ${node.title}`}
          >
            {busy ? "Creating…" : "Apply"}
          </button>
        )}
      </div>
      {node.expects ? <div className={styles.planNodeExpects}>{node.expects}</div> : null}
      <textarea
        className={styles.planGoalInput}
        value={draft}
        disabled={applied}
        rows={2}
        aria-label={`Goal for ${node.title}`}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void saveGoal()}
      />
      {rowError ? <div className={styles.error}>{rowError}</div> : null}
    </li>
  );
};

const OUTCOME_LABEL: Record<string, string> = {
  applied: "Applied",
  dismissed: "Dismissed",
  superseded: "Superseded by a newer proposal",
  stale: "The target changed since this was proposed — ask the agent to propose again",
};

/** What one Apply click does, per proposal kind — stated on the card. */
const EFFECT_LINE: Record<string, string> = {
  "node.create": "Applying adds this node to the canvas.",
  "project.install":
    "Applying installs only this project template — nothing is imported, attached, run, or published.",
  "node.template.create":
    "Applying registers the node type in this project and adds its first node.",
  "dataset.install":
    "Applying installs only this dataset into the project's Data Catalog — no agent is installed.",
};

/** dev/52 (+dev/59): the plan card's effect line — dynamic and honest about
 * removals. */
function planEffectLine(part: AgentProposalPart): string | null {
  if (part.tool !== "dataflow.plan.write" || !part.plan) return null;
  const n = part.plan.nodes.length;
  const removed = part.plan.removals?.length ?? 0;
  if (removed) {
    return (
      `Applying adds ${n} node${n === 1 ? "" : "s"} and removes ${removed} — ` +
      "removal deletes their content and cannot be undone."
    );
  }
  return `Applying adds these ${n} connected node${n === 1 ? "" : "s"} to the canvas — existing work is untouched.`;
}

/**
 * The review-before-apply card (memo dev/41; the blueprint's planned
 * `AgentReviewCard`). The agent proposes; the USER confirms here — Apply and
 * Dismiss are system review controls (the sanctioned exception family to
 * "no agent action buttons", same as the DEC-035 install dialog). The
 * proposed content is model output: it renders as inert plain text
 * (REQ-SEC-002), never markup. Non-pending proposals render inert with
 * their outcome label.
 */
export const AgentReviewCard: React.FC<{
  part: AgentProposalPart;
  /** Tint class carrying the agent's category color for the accent dot. */
  tintClassName?: string;
  onApply?: (proposalId: string) => Promise<void>;
  onDismiss?: (proposalId: string) => Promise<void>;
  /** dev/67-5 (plan proposals): the per-node review state from the
   * activeProposal mirror; enables the per-node rows when present. */
  planNodeState?: PlanNodeReviewState;
  onApplyPlanNode?: (proposalId: string, ref: string) => Promise<void>;
  onSavePlanGoal?: (proposalId: string, ref: string, goal: string) => Promise<void>;
  /** dev/67-8: apply plan edges (a subset by index, or all pending). */
  onApplyPlanEdges?: (proposalId: string, indices?: number[]) => Promise<void>;
}> = ({ part, tintClassName, onApply, onDismiss, planNodeState, onApplyPlanNode, onSavePlanGoal, onApplyPlanEdges }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [edgeBusy, setEdgeBusy] = useState<string | null>(null);

  const applyEdges = async (indices?: number[]) => {
    if (!onApplyPlanEdges || edgeBusy) return;
    setEdgeBusy(indices ? String(indices[0]) : "all");
    setError(null);
    try {
      await onApplyPlanEdges(part.proposalId, indices);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connecting failed");
    } finally {
      setEdgeBusy(null);
    }
  };

  const act = async (fn?: (proposalId: string) => Promise<void>) => {
    if (!fn || busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn(part.proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The review action failed");
    } finally {
      setBusy(false);
    }
  };

  const pending = part.status === "pending";
  return (
    <div className={styles.card} role="group" aria-label={`Review proposal: ${part.summary}`}>
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span>{part.summary}</span>
        <span className={styles.kind}>review</span>
      </div>
      {part.tool === "node.template.create" && part.justification ? (
        // The adequacy gate (dev/48 §3.2b): the model's reasoning is what the
        // user judges — rendered verbatim FIRST, above the definition.
        <div className={styles.justification} aria-label="Why a new node type is needed">
          {part.justification}
        </div>
      ) : null}
      {part.tool === "node.template.create" && part.template ? (
        <div className={styles.meta}>
          {part.template.label} · {part.template.engine}
          {part.template.description ? ` — ${part.template.description}` : ""}
        </div>
      ) : null}
      {part.tool === "dataflow.plan.write" && part.plan ? (
        // Summary first (dev/52): counts + goal at a glance; the node list
        // scrolls in the preview region below — plans can be large.
        <div className={styles.meta}>
          {part.plan.nodes.length} nodes · {part.plan.edgeCount} connections — {part.plan.goal}
        </div>
      ) : null}
      {part.tool === "dataflow.plan.write" && part.plan?.removals?.length ? (
        // DEC-049.2: removals reviewed by NAME — every victim, with a
        // content flag; impossible to miss.
        <div className={styles.removals} role="group" aria-label="Nodes this plan removes">
          <div className={styles.removalsTitle}>
            Removes {part.plan.removals.length} node
            {part.plan.removals.length === 1 ? "" : "s"}
            {part.plan.cascadeCount
              ? ` (and ${part.plan.cascadeCount} connected edge${part.plan.cascadeCount === 1 ? "" : "s"})`
              : ""}
          </div>
          <ul className={styles.removalsList}>
            {part.plan.removals.map((victim) => (
              <li key={victim.id}>
                {victim.label}
                {victim.nodeType ? ` · ${victim.nodeType}` : ""}
                {victim.contentChars > 0
                  ? ` — contains ${victim.contentChars} chars of content`
                  : " — empty"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {part.validation ? (
        // dev/67-7: the validation verdict — real runtime evidence, rendered
        // inert. PASS or FAIL, Apply stays available (labeled honestly).
        <div
          className={`${styles.validation} ${
            part.validation.verdict === "pass" ? styles.validationPass : styles.validationFail
          }`}
          role="status"
          aria-label={`Validation ${part.validation.verdict}`}
        >
          <span className={styles.validationBadge}>
            {part.validation.verdict === "pass" ? "PASS" : "FAIL"}
          </span>
          <span>
            {part.validation.verdict === "pass"
              ? `Executed through the dataflow${
                  part.validation.evidence?.outputDataType
                    ? ` — output: ${part.validation.evidence.outputDataType}`
                    : ""
                }`
              : part.validation.evidence?.kind === "upstream-blocker"
                ? `Upstream node ${part.validation.evidence?.blockerLabel ?? "?"} failed before this node ran`
                : (part.validation.evidence?.detail ??
                   `Validation failed after ${part.validation.rounds} round${part.validation.rounds === 1 ? "" : "s"}`)}
            {part.validation.rounds > 1
              ? ` (${part.validation.rounds} generation rounds)`
              : ""}
          </span>
          {part.validation.evidence?.stderrTail ? (
            <details className={styles.validationDetails}>
              <summary>error output</summary>
              <pre>{part.validation.evidence.stderrTail}</pre>
            </details>
          ) : null}
        </div>
      ) : null}
      {part.tool === "dataflow.plan.write" && part.plan && pending && onApplyPlanNode ? (
        // dev/67-5 (Simulation Mode: create): every planned node individually
        // inspectable — editable goal, expects, per-node Apply. Replaces the
        // text preview for pending plans; no generated code ever renders here
        // (plans are content-free by contract).
        <ul className={styles.planNodes} aria-label="Planned nodes">
          {part.plan.nodes.map((node) => (
            <PlanNodeRow
              key={node.ref}
              node={node}
              applied={(planNodeState?.appliedRefs ?? []).includes(node.ref)}
              goal={planNodeState?.editedGoals?.[node.ref] ?? node.intent}
              onApply={() => onApplyPlanNode(part.proposalId, node.ref)}
              onSaveGoal={(goal) =>
                onSavePlanGoal
                  ? onSavePlanGoal(part.proposalId, node.ref, goal)
                  : Promise.resolve()
              }
            />
          ))}
        </ul>
      ) : (
        <div className={styles.preview}>{part.preview}</div>
      )}
      {part.tool === "dataflow.plan.write" && part.plan?.edges?.length && pending && onApplyPlanEdges ? (
        // dev/67-8 (Simulation Mode: connect): edges reviewed BY NAME in a
        // vertical list — you always know which two nodes a click connects.
        <div className={styles.planEdges} role="group" aria-label="Planned connections">
          <div className={styles.planEdgesHead}>
            <span>Connections</span>
            <button
              type="button"
              className={styles.apply}
              disabled={edgeBusy !== null}
              onClick={() => void applyEdges()}
            >
              {edgeBusy === "all" ? "Connecting…" : "Connect all"}
            </button>
          </div>
          <ul className={styles.planEdgesList}>
            {part.plan.edges.map((edge, index) => {
              const state = planNodeState?.edgeStates?.[String(index)];
              const applied = planNodeState?.appliedRefs ?? [];
              const fromReady =
                !part.plan!.nodes.some((n) => n.ref === edge.from) || applied.includes(edge.from);
              const toReady =
                !part.plan!.nodes.some((n) => n.ref === edge.to) || applied.includes(edge.to);
              const blockedBy = !fromReady ? edge.fromLabel : !toReady ? edge.toLabel : null;
              return (
                <li key={index} className={styles.planEdgeRow}>
                  <span className={styles.planEdgeNames}>
                    {edge.fromLabel} → {edge.toLabel}
                    {edge.toHandle ? ` [${edge.toHandle}]` : ""}
                  </span>
                  {state === "applied" ? (
                    <span className={styles.planNodeCreated}>Connected ✓</span>
                  ) : state === "refused" ? (
                    <span className={styles.planEdgeRefused}>Refused ✗</span>
                  ) : (
                    <button
                      type="button"
                      className={styles.apply}
                      disabled={edgeBusy !== null || blockedBy !== null}
                      title={blockedBy ? `create '${blockedBy}' first` : undefined}
                      aria-label={`Connect ${edge.fromLabel} to ${edge.toLabel}`}
                      onClick={() => void applyEdges([index])}
                    >
                      {edgeBusy === String(index) ? "Connecting…" : "Connect"}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {planEffectLine(part) ? (
        <div className={styles.meta}>{planEffectLine(part)}</div>
      ) : EFFECT_LINE[part.tool] ? (
        <div className={styles.meta}>{EFFECT_LINE[part.tool]}</div>
      ) : null}
      {pending && (onApply || onDismiss) ? (
        <div className={styles.actions}>
          {onApply ? (
            <button
              type="button"
              className={styles.apply}
              disabled={busy}
              onClick={() => void act(onApply)}
            >
              {busy
                ? "Applying…"
                : part.validation?.verdict === "fail"
                  ? "Apply anyway"
                  : "Apply"}
            </button>
          ) : null}
          {onDismiss ? (
            <button
              type="button"
              className={styles.dismiss}
              disabled={busy}
              onClick={() => void act(onDismiss)}
            >
              Dismiss
            </button>
          ) : null}
        </div>
      ) : !pending ? (
        <div
          className={`${styles.outcome} ${
            styles[`outcome_${part.status}` as keyof typeof styles] ?? ""
          }`}
        >
          {OUTCOME_LABEL[part.status] ?? part.status}
        </div>
      ) : null}
      {error ? <div className={styles.error}>{error}</div> : null}
    </div>
  );
};
