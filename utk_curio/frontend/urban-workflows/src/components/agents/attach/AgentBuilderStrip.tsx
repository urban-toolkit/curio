import React, { useEffect, useState } from "react";
import type { AgentAttachment, AgentRemedy, AgentSolveWave } from "../../../api/agentsApi";
import { AddKeyAction } from "../../connectionKeys/AddKeyAction";
import { useFlowContext } from "../../../providers/FlowProvider";
import { AgentRunStatusLine } from "./AgentRunStatusLine";
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
  interrupted: 2, // dev/115: the server stopped mid-solve — Retry continues
  ready: 3,
};

/** dev/115: what a live pill state means, in words (never colour alone). */
const STATUS_LABEL: Record<string, string> = {
  solving: "solving",
  generating: "generating…",
  verifying: "verifying — running in the sandbox…",
  fixing: "fixing — the run failed, correcting…",
  verified: "solved ✓ verified",
  written: "written — no code to run; renders in the browser or its own service",
  solved: "solved",
  failed: "failed",
  skipped: "skipped",
  pending: "pending",
  proposed: "review pending",
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
  /** dev/106: the live batch's per-node failure reasons (nodeId → text) —
   * rendered ONCE per distinct reason under the pills, never per node. */
  solveErrors?: Record<string, string>;
  /** dev/116: the live batch's per-node remedies — rendered ONCE per host. */
  solveRemedies?: Record<string, AgentRemedy>;
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

  // dev/83: the shared running-status line (dot + elapsed + fraction) replaces
  // the bare "solving…" note — one status language with the reply meta lines.
  // One fixed label per batch kind; the fraction counts terminal node states.
  const liveJob = attachment.liveJob?.status === "running" ? attachment.liveJob : null;
  const activeBatchLabel =
    solving || phase === "solving" || liveJob?.kind === "solve-batch"
      ? "Solving"
      : simBusy === "auto"
        ? "Building"
        : simBusy === "step"
          ? "Stepping"
          : null;
  const batchDone = entries.filter(
    ([, s]) => s === "solved" || s === "verified" || s === "written" || s === "failed" || s === "skipped",
  ).length;
  const nodesDetail = entries.length > 0 ? `${batchDone}/${entries.length} nodes` : undefined;
  // dev/118: the wave in words when the batch runs in waves.
  const waveDetail =
    solveWave && solveWave.of > 1
      ? `wave ${solveWave.wave} of ${solveWave.of} — ${solveWave.nodeIds.length} node${solveWave.nodeIds.length === 1 ? "" : "s"}`
      : null;
  const batchDetail = [waveDetail, nodesDetail].filter(Boolean).join(" · ") || undefined;
  // Elapsed is strip-local observation time: builderSession persists no batch
  // start timestamp, so a panel reopened mid-run shows time since this strip
  // observed the batch (the dev/80 client-measured posture — nothing
  // fabricated). A label change (new batch kind) restarts the clock.
  const [batchStartedAt, setBatchStartedAt] = useState<number | null>(null);
  useEffect(() => {
    setBatchStartedAt(activeBatchLabel ? Date.now() : null);
  }, [activeBatchLabel]);

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
  // Apply/Dismiss target it directly. dev/67-9: a plan PARKED behind a
  // content review still drives the simulation controls.
  const planReview =
    attachment.activeProposal &&
    attachment.activeProposal.tool === "dataflow.plan.write" &&
    attachment.activeProposal.status === "pending"
      ? attachment.activeProposal
      : (attachment.planProposal?.status === "pending" ? attachment.planProposal : null);

  const pauseReason = session.pauseReason ?? null;

  // dev/106: the missing-specialist review, from the mirror — Solve minted a
  // reviewed `project.install` (REQ-ORCH-001) and this is where the failure
  // is, so this is where Install lives. Works without a transcript part.
  const installReview =
    attachment.activeProposal &&
    attachment.activeProposal.tool === "project.install" &&
    attachment.activeProposal.status === "pending"
      ? attachment.activeProposal
      : null;
  // One line per DISTINCT reason (six identical node failures → one line).
  const solveReasons = Array.from(new Set(Object.values(solveErrors ?? {}).filter(Boolean)));
  const solveNoticeLines = Array.from(new Set(Object.values(solveNotices ?? {}).filter(Boolean)));
  // dev/116: one action per host, whatever the number of nodes that need it.
  const remedies = Object.values(solveRemedies ?? {}).filter(
    (r, i, all) => r && r.host && all.findIndex((o) => o.kind === r.kind && o.host === r.host) === i,
  );

  const simulate = async (mode: "step" | "auto") => {
    if (!onSimulate || simBusy) return;
    setSimBusy(mode);
    setError(null);
    setNotice(null);
    try {
      const done = (await onSimulate(mode)) as { status?: string; reason?: { message?: string } } | undefined;
      if (done?.status === "paused" && done.reason?.message) {
        setNotice(`Paused — ${done.reason.message}`);
      } else if (done?.status === "cancelled") {
        setNotice("Simulation cancelled — everything already built stays.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "The simulation failed");
    } finally {
      setSimBusy(null);
    }
  };

  const review = async (
    fn?: (proposalId: string) => Promise<unknown>,
    proposalId: string | undefined = planReview?.proposalId,
  ) => {
    if (!fn || !proposalId || reviewBusy) return;
    setReviewBusy(true);
    setError(null);
    try {
      await fn(proposalId);
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
  const solveRunning = solving || phase === "solving" || liveJob?.kind === "solve-batch";
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
        {activeBatchLabel && batchStartedAt !== null ? (
          <AgentRunStatusLine
            display={{ kind: "running", startedAt: batchStartedAt }}
            runningLabel={activeBatchLabel}
            runningDetail={batchDetail}
            srLabel="Solve batch running"
          />
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
                {STATUS_LABEL[status] ?? status}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {solveReasons.length ? (
        <div className={styles.error} aria-live="polite">
          {solveReasons.map((r) => (
            <div key={r}>{r}</div>
          ))}
        </div>
      ) : null}
      {solveNoticeLines.length ? (
        <div className={styles.hint} role="note" aria-label="Solve notices">
          {solveNoticeLines.map((n) => (
            <div key={n}>{n}</div>
          ))}
        </div>
      ) : null}
      {remedies.length ? (
        <div className={styles.actions} role="group" aria-label="Missing connection keys">
          {remedies.map((r) => (
            <AddKeyAction key={`${r.kind}:${r.host}`} remedy={r} />
          ))}
        </div>
      ) : null}
      {installReview && (onApplyProposal || onDismissProposal) ? (
        <div className={styles.actions} role="group" aria-label="Missing specialist">
          <span className={styles.reviewSummary}>
            Solve needs a specialist — {installReview.summary}
          </span>
          {onApplyProposal ? (
            <button
              type="button"
              className={styles.solve}
              disabled={reviewBusy || solving}
              onClick={() => void review(onApplyProposal, installReview.proposalId)}
            >
              {reviewBusy ? "Adding…" : "Add to project"}
            </button>
          ) : null}
          {onDismissProposal ? (
            <button
              type="button"
              className={styles.run}
              disabled={reviewBusy}
              onClick={() => void review(onDismissProposal, installReview.proposalId)}
            >
              Dismiss
            </button>
          ) : null}
        </div>
      ) : null}
      {planReview && (onSimulate || onApplyProposal || onDismissProposal) ? (
        <div className={styles.actions} role="group" aria-label="Plan review">
          <span className={styles.reviewSummary}>{planReview.summary}</span>
          {onSimulate ? (
            // dev/67-9 (DEC-054): the validated sequence is the DEFAULT —
            // bulk apply survives only as the explicit secondary action.
            <>
              <button
                type="button"
                className={styles.solve}
                disabled={simBusy !== null || reviewBusy}
                onClick={() => void simulate("auto")}
              >
                {simBusy === "auto"
                  ? "Building…"
                  : pauseReason
                    ? "Resume"
                    : "Build & validate plan"}
              </button>
              <button
                type="button"
                className={styles.run}
                disabled={simBusy !== null || reviewBusy}
                onClick={() => void simulate("step")}
              >
                {simBusy === "step" ? "Stepping…" : "Step"}
              </button>
            </>
          ) : null}
          {simBusy && onCancelSimulate ? (
            <button
              type="button"
              className={styles.run}
              onClick={() => void onCancelSimulate()}
            >
              Cancel
            </button>
          ) : null}
          {onApplyProposal ? (
            <button
              type="button"
              className={styles.run}
              disabled={reviewBusy || simBusy !== null}
              onClick={() => void review(onApplyProposal)}
            >
              {reviewBusy
                ? "Applying…"
                : onSimulate
                  ? "Apply all without validation"
                  : "Apply plan"}
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
          disabled={solveRunning || Boolean(solveDisabledReason)}
          title={
            solveDisabledReason ??
            (phase === "interrupted"
              ? "A new execution linked to the interrupted one — nothing is replayed"
              : "Data-loading nodes run in the sandbox and are fixed before their code is written")
          }
          onClick={() => void solve(failed.length && !pending.length ? failed : undefined)}
        >
          {solveRunning
            ? "Solving…"
            : phase === "interrupted"
              ? `Retry ${unresolved} interrupted`
              : failed.length && !pending.length
                ? `Retry ${failed.length} failed`
                : "Solve"}
        </button>
        {onCancelSolve && solveRunning ? (
          <button
            type="button"
            className={styles.run}
            disabled={cancelling}
            title="Stops after the current node finishes — a running fetch cannot be aborted"
            onClick={() => void cancel()}
          >
            {cancelling ? "Cancelling…" : "Cancel"}
          </button>
        ) : null}
        <button
          type="button"
          className={styles.run}
          disabled={phase !== "ready" || Boolean(runDisabledReason) || isRunActive}
          title={runDisabledReason ?? (isRunActive ? "A run is already in progress" : undefined)}
          onClick={() => playAllNodes()}
        >
          Run workflow
        </button>
      </div>
      {solveDisabledReason && phase !== "ready" ? (
        <div className={styles.hint}>{solveDisabledReason}</div>
      ) : null}
      {solveRunning ? (
        // dev/115 (DEC-021 slice): the batch is a background job.
        <div className={styles.hint}>Solve keeps running if you close this panel.</div>
      ) : null}
      {phase === "interrupted" ? (
        <div className={styles.hint} role="status">
          Solve was interrupted — the server stopped while it was running. Finished nodes kept
          their content; nothing was replayed. Retry continues from what is still pending.
        </div>
      ) : null}
      {simulationActivity ? (
        <div className={styles.hint} aria-live="polite">{simulationActivity}</div>
      ) : null}
      {!simBusy && pauseReason ? (
        <div className={styles.hint}>
          Paused — {pauseReason.message} (Resume continues from here.)
        </div>
      ) : null}
      {notice ? <div className={styles.hint}>{notice}</div> : null}
      {error ? <div className={styles.error}>{error}</div> : null}
    </div>
  );
};
