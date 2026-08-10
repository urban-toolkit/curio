import React, { useState } from "react";
import type { AgentAttachment } from "../../../api/agentsApi";
import { useFlowContext } from "../../../providers/FlowProvider";
import { BUILDER_TEMPLATES } from "./builderTemplates";
import styles from "./AgentBuilderStrip.module.css";

const PHASES: Array<{ id: string; label: string }> = [
  { id: "idle", label: "Plan" },
  { id: "plan_review", label: "Review" },
  { id: "applied", label: "Solve" },
  { id: "ready", label: "Ready" },
];

const PHASE_RANK: Record<string, number> = {
  idle: 0,
  plan_review: 1,
  simulating: 2, // dev/67-5: per-node create/solve in progress
  applied: 2,
  solving: 2,
  ready: 3,
};

/**
 * The dev/52 DR-5 phase-aware builder strip — rendered only for Dataflow
 * Builder attachments, inside the existing chat drawer (no new surface).
 * Everything derives from the server-owned `builderSession` (DR-2): phase
 * chips, per-node solve progress, Solve/Retry, and Run workflow via the
 * existing `playAllNodes`. Disabled states explain themselves; templates
 * seed the goal prompt through the caller's prefill rule.
 */
export const AgentBuilderStrip: React.FC<{
  attachment: AgentAttachment;
  onSolve: (nodeIds?: string[]) => Promise<unknown>;
  /** dev/63: the live batch's transient per-node statuses (nodeId → status,
   * including "solving") — overlays the persisted nodeRuns for display. */
  solveProgress?: Record<string, string>;
  /** dev/63: cancel the running solve — in-flight children finish; the rest
   * revert to pending. Omitted → no Cancel control. */
  onCancelSolve?: () => Promise<void>;
  onComposePrompt: (prompt: string) => void;
  /** The dev/41 system review actions — surfaced here during plan_review
   * (dev/53) so the Apply control lives where the phase indicator points,
   * targeting the activeProposal mirror (works even when a transcript part
   * is missing). Omitted → the transcript card is the only review surface. */
  onApplyProposal?: (proposalId: string) => Promise<void>;
  onDismissProposal?: (proposalId: string) => Promise<void>;
}> = ({
  attachment,
  onSolve,
  solveProgress,
  onCancelSolve,
  onComposePrompt,
  onApplyProposal,
  onDismissProposal,
}) => {
  const { playAllNodes } = useFlowContext();
  const [solving, setSolving] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const session = attachment.builderSession ?? { phase: "idle" as const };
  const phase = session.phase ?? "idle";
  const nodeRuns = session.nodeRuns ?? {};
  // The live overlay wins per node while the batch streams (dev/63); the
  // persisted session takes back over on the terminal refetch.
  const entries = Object.entries({ ...nodeRuns, ...(solveProgress ?? {}) });
  const pending = entries.filter(([, s]) => s === "pending").map(([id]) => id);
  const failed = entries.filter(([, s]) => s === "failed").map(([id]) => id);
  const unresolved = pending.length + failed.length;

  const solve = async (nodeIds?: string[]) => {
    setSolving(true);
    setError(null);
    setNotice(null);
    try {
      const result = (await onSolve(nodeIds)) as
        | { cancelled?: boolean; notAttempted?: string[] }
        | undefined;
      if (result?.cancelled) {
        const skipped = result.notAttempted?.length ?? 0;
        setNotice(
          skipped
            ? `Cancelled — ${skipped} node${skipped === 1 ? "" : "s"} not attempted`
            : "Cancelled — all dispatched nodes finished",
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Solve failed");
    } finally {
      setSolving(false);
      setCancelling(false);
    }
  };

  const cancel = async () => {
    if (!onCancelSolve || cancelling) return;
    setCancelling(true);
    try {
      await onCancelSolve();
    } catch {
      setCancelling(false);
    }
  };

  // The pending plan review, from the fast mirror (dev/41): the strip's
  // Apply/Dismiss target it directly.
  const planReview =
    attachment.activeProposal &&
    attachment.activeProposal.tool === "dataflow.plan.write" &&
    attachment.activeProposal.status === "pending"
      ? attachment.activeProposal
      : null;

  const review = async (fn?: (proposalId: string) => Promise<void>) => {
    if (!fn || !planReview || reviewBusy) return;
    setReviewBusy(true);
    setError(null);
    try {
      await fn(planReview.proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The review action failed");
    } finally {
      setReviewBusy(false);
    }
  };

  const solveDisabledReason =
    phase === "plan_review"
      ? "Apply or dismiss the plan review first"
      : phase === "idle"
        ? "Apply a plan first"
        : unresolved === 0
          ? "No pending nodes"
          : null;
  const runDisabledReason =
    unresolved > 0 ? `${unresolved} node${unresolved === 1 ? "" : "s"} unsolved` : null;

  return (
    <div className={styles.strip} role="group" aria-label="Dataflow Builder">
      <div className={styles.phases} aria-label="Phase">
        {PHASES.map((p) => (
          <span
            key={p.id}
            className={`${styles.phaseChip} ${
              PHASE_RANK[phase] === PHASE_RANK[p.id] ? styles.phaseActive : ""
            }`}
            aria-current={PHASE_RANK[phase] === PHASE_RANK[p.id] ? "step" : undefined}
          >
            {p.label}
          </span>
        ))}
        {phase === "solving" || solving ? (
          <span className={styles.solvingNote}>solving…</span>
        ) : null}
      </div>
      {phase === "idle" ? (
        <div className={styles.templates} role="group" aria-label="Planning templates">
          {BUILDER_TEMPLATES.map((t) => (
            <button
              key={t.id}
              type="button"
              className={styles.templateChip}
              onClick={() => onComposePrompt(t.seed)}
            >
              {t.label}
            </button>
          ))}
        </div>
      ) : null}
      {entries.length > 0 ? (
        <ul className={styles.nodeRuns} aria-live="polite" aria-label="Plan node progress">
          {entries.map(([nodeId, status]) => (
            <li key={nodeId} className={styles.nodeRun}>
              <span className={styles.nodeId}>{nodeId.slice(0, 8)}</span>
              <span className={styles[`status_${status}` as keyof typeof styles] ?? ""}>
                {status}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {planReview && (onApplyProposal || onDismissProposal) ? (
        <div className={styles.actions} role="group" aria-label="Plan review">
          <span className={styles.reviewSummary}>{planReview.summary}</span>
          {onApplyProposal ? (
            <button
              type="button"
              className={styles.solve}
              disabled={reviewBusy}
              onClick={() => void review(onApplyProposal)}
            >
              {reviewBusy ? "Applying…" : "Apply plan"}
            </button>
          ) : null}
          {onDismissProposal ? (
            <button
              type="button"
              className={styles.run}
              disabled={reviewBusy}
              onClick={() => void review(onDismissProposal)}
            >
              Dismiss
            </button>
          ) : null}
        </div>
      ) : null}
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.solve}
          disabled={solving || phase === "solving" || Boolean(solveDisabledReason)}
          title={solveDisabledReason ?? undefined}
          onClick={() => void solve(failed.length && !pending.length ? failed : undefined)}
        >
          {solving || phase === "solving"
            ? "Solving…"
            : failed.length && !pending.length
              ? `Retry ${failed.length} failed`
              : "Solve"}
        </button>
        {onCancelSolve && (solving || phase === "solving") ? (
          <button
            type="button"
            className={styles.run}
            disabled={cancelling}
            onClick={() => void cancel()}
          >
            {cancelling ? "Cancelling…" : "Cancel"}
          </button>
        ) : null}
        <button
          type="button"
          className={styles.run}
          disabled={phase !== "ready" || Boolean(runDisabledReason)}
          title={runDisabledReason ?? undefined}
          onClick={() => playAllNodes()}
        >
          Run workflow
        </button>
      </div>
      {solveDisabledReason && phase !== "ready" ? (
        <div className={styles.hint}>{solveDisabledReason}</div>
      ) : null}
      {notice ? <div className={styles.hint}>{notice}</div> : null}
      {error ? <div className={styles.error}>{error}</div> : null}
    </div>
  );
};
