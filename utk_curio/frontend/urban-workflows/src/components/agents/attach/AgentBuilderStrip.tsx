import React, { useEffect, useState } from "react";
import type { AgentAttachment, AgentRemedy, AgentSolveWave } from "../../../services/agents";
import { AddKeyAction } from "../../connectionKeys/AddKeyAction";
import { LlmConfigAction, remedyOf } from "../../llmConfigs/LlmConfigAction";
import { OpenDatasetFinderAction } from "./OpenDatasetFinderAction";
import { useFlowContext } from "../../../providers/FlowProvider";
import styles from "./AgentBuilderStrip.module.css";
import { BatchActions } from "./builderStrip/BatchActions";
import { MissingSpecialistReview } from "./builderStrip/MissingSpecialistReview";
import { NodeRunPills } from "./builderStrip/NodeRunPills";
import { PhaseChips } from "./builderStrip/PhaseChips";
import { PlanReviewActions } from "./builderStrip/PlanReviewActions";
import { PlanningTemplates } from "./builderStrip/PlanningTemplates";
import { SolveFeedback } from "./builderStrip/SolveFeedback";
import {
  batchDetailFor,
  distinctLines,
  passLineText,
  remediesByHost,
  selectionRemediesOf,
  sessionEndingText,
  solveDisabledReasonFor,
} from "./builderStrip/builderStripDerived";

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
  /** dev/106: the live batch's per-node failure reasons (nodeId → text) —
   * rendered ONCE per distinct reason under the pills, never per node. */
  solveErrors?: Record<string, string>;
  /** dev/116: the live batch's per-node remedies — rendered ONCE per host.
   * dev/126: a `dataset-selection` remedy is rendered per NODE instead (each
   * one opens a different chat). */
  solveRemedies?: Record<string, AgentRemedy>;
  /** dev/126: open a node's Dataset Finder chat (the awaiting-selection
   * remedy's action). Omitted → the reason line stands alone. */
  onOpenChat?: (attachmentId: string) => void;
  /** dev/131: what the running session is blocked on, per node — the live
   * `solve_pass`/`solve_waiting` summary. A node whose `kind` is
   * "dataset-selection" is waiting for the USER. */
  solveWaiting?: Array<{
    nodeId: string;
    kind: string;
    reason?: string;
    attachmentId?: string | null;
  }>;
  /** dev/131: how the last session ended — complete | stopped | budget | blocked. */
  solveEndedBy?: string | null;
  /** dev/131: the session's pass number while it runs. */
  solvePass?: number | null;
  /** dev/131: resolve ONE node through its own agent (the per-node Solve).
   *  Omitted → the pills carry no action. */
  onSolveNode?: (nodeId: string) => Promise<unknown>;
  /** dev/118: the live batch's current wave — "solving wave 2 of 3 — 4 nodes". */
  solveWave?: AgentSolveWave;
  /** dev/118: per-node notices that are not errors — ONE line per distinct text. */
  solveNotices?: Record<string, string>;
  /** dev/63: cancel the running solve — in-flight children finish; the rest
   * revert to pending. Omitted → no Cancel control. */
  onCancelSolve?: () => Promise<void>;
  onComposePrompt: (prompt: string) => void;
  /** The dev/41 system review actions — surfaced here during plan_review
   * (dev/53) so the Apply control lives where the phase indicator points,
   * targeting the activeProposal mirror (works even when a transcript part
   * is missing). Omitted → the transcript card is the only review surface. */
  onApplyProposal?: (proposalId: string) => Promise<unknown>;
  onDismissProposal?: (proposalId: string) => Promise<void>;
  /** dev/67-9: the Simulation Mode driver — step or auto (Build & validate). */
  onSimulate?: (mode: "step" | "auto") => Promise<unknown>;
  onCancelSimulate?: () => Promise<void>;
  /** dev/67-9: the running simulation's narration line. */
  simulationActivity?: string;
}> = ({
  attachment,
  onSolve,
  solveProgress,
  solveErrors,
  solveRemedies,
  onOpenChat,
  solveWaiting,
  solveEndedBy,
  solvePass,
  onSolveNode,
  solveWave,
  solveNotices,
  onCancelSolve,
  onComposePrompt,
  onApplyProposal,
  onDismissProposal,
  onSimulate,
  onCancelSimulate,
  simulationActivity,
}) => {
  const { playAllNodes, isRunActive } = useFlowContext();
  const [solving, setSolving] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [simBusy, setSimBusy] = useState<"step" | "auto" | null>(null);
  const [nodeSolving, setNodeSolving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The refusal's remedy, when it has one (no LLM configuration answers a
  // delegate this run relies on).
  const [errorRemedy, setErrorRemedy] = useState<AgentRemedy | null>(null);
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

  // dev/83: the shared running-status line (dot + elapsed + fraction) replaces
  // the bare "solving…" note. One fixed label per batch kind.
  const liveJob = attachment.liveJob?.status === "running" ? attachment.liveJob : null;
  const activeBatchLabel =
    solving || phase === "solving" || liveJob?.kind === "solve-batch"
      ? "Solving"
      : simBusy === "auto"
        ? "Building"
        : simBusy === "step"
          ? "Stepping"
          : null;
  // Elapsed is strip-local observation time: builderSession persists no batch
  // start timestamp, so a panel reopened mid-run shows time since this strip
  // observed the batch (the dev/80 client-measured posture). A label change
  // (new batch kind) restarts the clock.
  const [batchStartedAt, setBatchStartedAt] = useState<number | null>(null);
  useEffect(() => {
    setBatchStartedAt(activeBatchLabel ? Date.now() : null);
  }, [activeBatchLabel]);

  const solve = async (nodeIds?: string[]) => {
    setSolving(true);
    setError(null);
    setErrorRemedy(null);
    setNotice(null);
    try {
      const result = (await onSolve(nodeIds)) as { cancelled?: boolean; notAttempted?: string[] } | undefined;
      if (result?.cancelled) {
        const skipped = result.notAttempted?.length ?? 0;
        setNotice(
          skipped
            ? `Cancelled: ${skipped} node${skipped === 1 ? "" : "s"} not attempted`
            : "Cancelled: all dispatched nodes finished",
        );
      }
    } catch (e) {
      setErrorRemedy(remedyOf(e));
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

  // The pending plan review, from the fast mirror (dev/41); dev/67-9: a plan
  // PARKED behind a content review still drives the simulation controls.
  const planReview =
    attachment.activeProposal &&
    attachment.activeProposal.tool === "dataflow.plan.write" &&
    attachment.activeProposal.status === "pending"
      ? attachment.activeProposal
      : (attachment.planProposal?.status === "pending" ? attachment.planProposal : null);
  const pauseReason = session.pauseReason ?? null;
  // dev/106: the missing-specialist review, from the mirror.
  const installReview =
    attachment.activeProposal &&
    attachment.activeProposal.tool === "project.install" &&
    attachment.activeProposal.status === "pending"
      ? attachment.activeProposal
      : null;

  const simulate = async (mode: "step" | "auto") => {
    if (!onSimulate || simBusy) return;
    setSimBusy(mode);
    setError(null);
    setErrorRemedy(null);
    setNotice(null);
    try {
      const done = (await onSimulate(mode)) as { status?: string; reason?: { message?: string } } | undefined;
      if (done?.status === "paused" && done.reason?.message) {
        setNotice(`Paused: ${done.reason.message}`);
      } else if (done?.status === "cancelled") {
        setNotice("Simulation cancelled; everything already built stays.");
      }
    } catch (e) {
      setErrorRemedy(remedyOf(e));
      setError(e instanceof Error ? e.message : "The simulation failed");
    } finally {
      setSimBusy(null);
    }
  };

  // dev/131: "users should have the ability to resolve each node
  // individually" — the node's OWN agent runs the same verified loop.
  const solveOne = async (nodeId: string) => {
    if (!onSolveNode || nodeSolving) return;
    setNodeSolving(nodeId);
    setError(null);
    setErrorRemedy(null);
    try {
      await onSolveNode(nodeId);
    } catch (e) {
      setErrorRemedy(remedyOf(e));
      setError(e instanceof Error ? e.message : "Solving that node failed");
    } finally {
      setNodeSolving(null);
    }
  };

  const review = async (
    fn?: (proposalId: string) => Promise<unknown>,
    proposalId: string | undefined = planReview?.proposalId,
  ) => {
    if (!fn || !proposalId || reviewBusy) return;
    setReviewBusy(true);
    setError(null);
    setErrorRemedy(null);
    try {
      await fn(proposalId);
    } catch (e) {
      setErrorRemedy(remedyOf(e));
      setError(e instanceof Error ? e.message : "The review action failed");
    } finally {
      setReviewBusy(false);
    }
  };

  const userBlocked = (solveWaiting ?? []).filter((w) => w.kind === "dataset-selection");
  const userBlockedIds = new Set(userBlocked.map((w) => w.nodeId));
  const everyUnresolvedNeedsUser =
    unresolved > 0 && pending.concat(failed).every((id) => userBlockedIds.has(id));
  const solveDisabledReason = solveDisabledReasonFor({
    phase, unresolved, everyUnresolvedNeedsUser, userBlockedCount: userBlocked.length,
  });
  const solveRunning = solving || phase === "solving" || liveJob?.kind === "solve-batch";
  const runDisabledReason =
    unresolved > 0 ? `${unresolved} node${unresolved === 1 ? "" : "s"} unsolved` : null;

  return (
    <div className={styles.strip} role="group" aria-label="Dataflow Builder">
      <PhaseChips
        phase={phase}
        activeBatchLabel={activeBatchLabel}
        batchStartedAt={batchStartedAt}
        batchDetail={batchDetailFor(entries, solveWave)}
      />
      {phase === "idle" ? <PlanningTemplates onComposePrompt={onComposePrompt} /> : null}
      {entries.length > 0 ? (
        <NodeRunPills
          entries={entries}
          userBlockedIds={userBlockedIds}
          solveWaiting={solveWaiting}
          solveRunning={solveRunning}
          nodeSolving={nodeSolving}
          onSolveNode={onSolveNode ? (nodeId) => void solveOne(nodeId) : undefined}
        />
      ) : null}
      {solveRunning && (solvePass ?? 0) > 0 ? (
        <div className={styles.hint} aria-live="polite">
          {passLineText(solvePass as number, unresolved, userBlocked.length)}
        </div>
      ) : null}
      {!solveRunning && solveEndedBy ? (
        <div className={styles.hint} role="status">
          {sessionEndingText(solveEndedBy, unresolved)}
        </div>
      ) : null}
      <SolveFeedback
        reasons={distinctLines(solveErrors)}
        notices={distinctLines(solveNotices)}
        remedies={remediesByHost(solveRemedies)}
        selectionRemedies={selectionRemediesOf(solveRemedies)}
        onOpenChat={onOpenChat}
      />
      {installReview && (onApplyProposal || onDismissProposal) ? (
        <MissingSpecialistReview
          review={installReview}
          reviewBusy={reviewBusy}
          solving={solving}
          onApply={onApplyProposal ? () => void review(onApplyProposal, installReview.proposalId) : undefined}
          onDismiss={onDismissProposal ? () => void review(onDismissProposal, installReview.proposalId) : undefined}
        />
      ) : null}
      {planReview && (onSimulate || onApplyProposal || onDismissProposal) ? (
        <PlanReviewActions
          review={planReview}
          paused={Boolean(pauseReason)}
          simBusy={simBusy}
          reviewBusy={reviewBusy}
          onSimulate={onSimulate ? (mode) => void simulate(mode) : undefined}
          onCancelSimulate={onCancelSimulate ? () => void onCancelSimulate() : undefined}
          onApply={onApplyProposal ? () => void review(onApplyProposal) : undefined}
          onDismiss={onDismissProposal ? () => void review(onDismissProposal) : undefined}
        />
      ) : null}
      <BatchActions
        phase={phase}
        solveRunning={solveRunning}
        solveDisabledReason={solveDisabledReason}
        unresolved={unresolved}
        failedCount={failed.length}
        pendingCount={pending.length}
        cancelling={cancelling}
        runDisabledReason={runDisabledReason}
        isRunActive={isRunActive}
        onSolve={() => void solve(failed.length && !pending.length ? failed : undefined)}
        onCancel={onCancelSolve ? () => void cancel() : undefined}
        onRun={() => playAllNodes()}
      />
      {solveDisabledReason && phase !== "ready" ? <div className={styles.hint}>{solveDisabledReason}</div> : null}
      {solveRunning ? (
        // dev/115 (DEC-021 slice): the batch is a background job.
        <div className={styles.hint}>Solve keeps running if you close this panel.</div>
      ) : null}
      {phase === "interrupted" ? (
        <div className={styles.hint} role="status">
          Solve was interrupted: the server stopped while it was running. Finished nodes kept
          their content; nothing was replayed. Retry continues from what is still pending.
        </div>
      ) : null}
      {simulationActivity ? (
        <div className={styles.hint} aria-live="polite">{simulationActivity}</div>
      ) : null}
      {!simBusy && pauseReason ? (
        <div className={styles.hint}>Paused — {pauseReason.message} (Resume continues from here.)</div>
      ) : null}
      {notice ? <div className={styles.hint}>{notice}</div> : null}
      {error ? (
        <div className={styles.error}>
          {error} <LlmConfigAction remedy={errorRemedy} />
        </div>
      ) : null}
    </div>
  );
};
