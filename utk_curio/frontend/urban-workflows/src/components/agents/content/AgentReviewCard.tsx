import React, { useState } from "react";
import type { AgentProposalPart } from "../../../api/agentsApi";
import styles from "./AgentReviewCard.module.css";

/** dev/67-5: the per-node review state (from the activeProposal mirror). */
export interface PlanNodeReviewState {
  appliedRefs: string[];
  editedGoals: Record<string, string>;
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
}> = ({ part, tintClassName, onApply, onDismiss, planNodeState, onApplyPlanNode, onSavePlanGoal }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
              {busy ? "Applying…" : "Apply"}
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
