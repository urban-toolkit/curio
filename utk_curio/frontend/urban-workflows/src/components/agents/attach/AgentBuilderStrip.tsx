import React, { useEffect, useId, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faChevronUp } from "@fortawesome/free-solid-svg-icons";
import type { AgentAttachment, AgentRemedy, AgentSolveWave } from "../../../services/agents";
import { LlmConfigAction, remedyOf } from "../../llmConfigs/LlmConfigAction";
import { useFlowContext } from "../../../providers/FlowProvider";
import { nodeLabel } from "../../scenarios/scenarioLabels";
import { AgentRunStatusLine } from "./AgentRunStatusLine";
import styles from "./AgentBuilderStrip.module.css";
import { BatchActions, type BatchPart } from "./builderStrip/BatchActions";
import { MissingSpecialistReview } from "./builderStrip/MissingSpecialistReview";
import { NodeRunPills } from "./builderStrip/NodeRunPills";
import { PlanBuildActions } from "./builderStrip/PlanBuildActions";
import { SolveFeedback, SolveRemedies } from "./builderStrip/SolveFeedback";
import {
  batchDetailFor,
  distinctLines,
  inPlanOrder,
  mainActionOf,
  passLineText,
  planLeftToBuild,
  planLineWords,
  remediesByHost,
  selectionRemediesOf,
  sessionEndingText,
  solveDisabledReasonFor,
} from "./builderStrip/builderStripDerived";

/** The more part's toggle, by what a click on it does. */
export const SHOW_PLAN_MORE = "Show the plan's nodes and actions";
export const HIDE_PLAN_MORE = "Hide the plan's nodes and actions";

/** Why no Solve is offered while a build of the plan runs. */
export const BUILD_RUNNING_HINT = "The plan is being built: Stop the build to Solve";

/**
 * The plan line of an agent that declares dataflow.orchestrate (dev/52 DR-5),
 * under the chat's Goal line. Everything derives from the server-owned
 * `builderSession` (DR-2).
 *
 * The line says the phase in words, its counts and who it waits for, and
 * holds one main action: Solve (or Retry), Stop while a batch or a build runs,
 * Resume when a build paused, Run workflow once the plan is ready. While a
 * build runs no Solve is offered, the plan's or a node's: a build is a stream
 * over the plan, not an agent job, and a Solve would run over the same nodes.
 * Its more part, closed until asked for, holds the plan's nodes with their own
 * Solve, Build & validate plan, Step, the other batch actions and the hints,
 * at most a third of the panel's height, scrolling. What comes with a fix
 * stays in view under the line: a missing key's Add key, a missing
 * specialist's Add to project, the nodes awaiting a source, an action's error
 * with its Open API Settings. Before any plan there is no line: the planning
 * templates are in the empty conversation.
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
  /** dev/126: open the chat of a node's agent that finds its datasets (the
   * awaiting-selection remedy's action). Omitted → the reason line stands alone. */
  onOpenChat?: (attachmentId: string) => void;
  /** The name of the agent an attachment of this dataflow binds, from the
   * live list: the buttons and pills for a node awaiting a source name it. */
  agentNameOf?: (attachmentId: string) => string | null;
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
   * revert to pending. Omitted → no Stop control. */
  onCancelSolve?: () => Promise<void>;
  /** The dev/41 review actions of an install this agent needs (a missing
   * specialist, dev/106), surfaced under the line, where its Retry is.
   * Omitted → the transcript card is the only review surface. */
  onApplyProposal?: (proposalId: string) => Promise<unknown>;
  onDismissProposal?: (proposalId: string) => Promise<void>;
  /** dev/67-9: Build & validate over the landed plan: step or auto. */
  onSimulate?: (mode: "step" | "auto") => Promise<unknown>;
  onCancelSimulate?: () => Promise<void>;
  /** dev/67-9: the running simulation's narration line. */
  simulationActivity?: string;
  /** The build the chat runs for this agent, step or auto, which outlives
   *  this line: drawn again (the chat opened again, or the rail back on this
   *  agent), the line still shows it and its Stop. Omitted, only a build this
   *  line started. */
  simulating?: "step" | "auto" | null;
}> = ({
  attachment,
  onSolve,
  solveProgress,
  solveErrors,
  solveRemedies,
  onOpenChat,
  agentNameOf,
  solveWaiting,
  solveEndedBy,
  solvePass,
  onSolveNode,
  solveWave,
  solveNotices,
  onCancelSolve,
  onApplyProposal,
  onDismissProposal,
  onSimulate,
  onCancelSimulate,
  simulationActivity,
  simulating = null,
}) => {
  const { playAllNodes, isRunActive: browserRunActive, serverRunActive, nodes } = useFlowContext();
  const isRunActive = browserRunActive || serverRunActive;
  // Each plan node by the name its header shows, its title, else its
  // template's label; its short id only when it is not on the canvas.
  const flowNodes: Array<{ id: string; data?: unknown }> = Array.isArray(nodes) ? nodes : [];
  const nodeNameOf = (nodeId: string): string =>
    nodeLabel(flowNodes.find((node) => node.id === nodeId), nodeId);
  const [solving, setSolving] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [simBusy, setSimBusy] = useState<"step" | "auto" | null>(null);
  // A build this line started, or one the chat still runs for this agent.
  const building = simBusy ?? simulating;
  // Its Stop was asked for: the build stops after its current step.
  const [buildStopping, setBuildStopping] = useState(false);
  useEffect(() => {
    if (!building) setBuildStopping(false);
  }, [building]);
  const [nodeSolving, setNodeSolving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The refusal's remedy, when it has one (no LLM configuration answers a
  // delegate this run relies on).
  const [errorRemedy, setErrorRemedy] = useState<AgentRemedy | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // The more part opens only when asked for, and stays as it was across the
  // session's updates.
  const [moreOpen, setMoreOpen] = useState(false);
  const moreId = useId();

  const session = attachment.builderSession ?? { phase: "idle" as const };
  const phase = session.phase ?? "idle";
  const nodeRuns = session.nodeRuns ?? {};
  // The live overlay wins per node while the batch streams (dev/63); the
  // persisted session takes back over on the terminal refetch. The pills
  // read in the plan's order, as its card lists its nodes, and so do the
  // Open Dataset Finder buttons of the nodes awaiting a source.
  const canvasIds = flowNodes.map((node) => node.id);
  const entries = inPlanOrder(
    Object.entries({ ...nodeRuns, ...(solveProgress ?? {}) }),
    attachment.planProposal,
    canvasIds,
  );
  const selectionRemedies = inPlanOrder(selectionRemediesOf(solveRemedies), attachment.planProposal, canvasIds);
  const pending = entries.filter(([, s]) => s === "pending").map(([id]) => id);
  const failed = entries.filter(([, s]) => s === "failed").map(([id]) => id);
  const unresolved = pending.length + failed.length;

  // dev/83: the shared running-status line (dot + elapsed + fraction) replaces
  // the bare "solving…" note. One fixed label per batch kind.
  const liveJob = attachment.liveJob?.status === "running" ? attachment.liveJob : null;
  const activeBatchLabel =
    solving || phase === "solving" || liveJob?.kind === "solve-batch"
      ? "Solving"
      : building === "auto"
        ? "Building"
        : building === "step"
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

  // The plan that landed, while any of its nodes is left to build: Build &
  // validate and Step work on it.
  const landedPlan = planLeftToBuild(attachment.planProposal, session) ? attachment.planProposal! : null;
  const pauseReason = session.pauseReason ?? null;
  // dev/106: the missing-specialist review, from the mirror.
  const installReview =
    attachment.activeProposal &&
    attachment.activeProposal.tool === "project.install" &&
    attachment.activeProposal.status === "pending"
      ? attachment.activeProposal
      : null;

  const simulate = async (mode: "step" | "auto") => {
    if (!onSimulate || building) return;
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

  // The build's Stop, the line's action while it runs: it stops after its
  // current step, and what it built stays.
  const stopBuild = async () => {
    if (!onCancelSimulate || buildStopping) return;
    setBuildStopping(true);
    try {
      await onCancelSimulate();
    } catch {
      setBuildStopping(false);
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

  const review = async (fn: ((proposalId: string) => Promise<unknown>) | undefined, proposalId: string) => {
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
  // While a build runs no Solve is offered: it would run over the same nodes.
  const solveDisabledReason = building
    ? BUILD_RUNNING_HINT
    : solveDisabledReasonFor({
        phase, unresolved, everyUnresolvedNeedsUser, userBlockedCount: userBlocked.length,
      });
  const solveRunning = solving || phase === "solving" || liveJob?.kind === "solve-batch";
  // A batch's Stop reads Stopping… until that batch ends, however it ends: one
  // this line did not start (another tab's, or one a chat opened again found
  // running) has no Solve of this line's whose end would put it back.
  useEffect(() => {
    if (!solveRunning) setCancelling(false);
  }, [solveRunning]);
  const runDisabledReason =
    unresolved > 0 ? `${unresolved} node${unresolved === 1 ? "" : "s"} unsolved` : null;

  const paused = !building && Boolean(pauseReason);
  const main = mainActionOf({
    solveRunning,
    canStopSolve: Boolean(onCancelSolve),
    building: Boolean(building),
    canStopBuild: Boolean(onCancelSimulate),
    paused: paused && Boolean(landedPlan && onSimulate),
    phase,
  });
  const words = planLineWords({ phase, paused, nodes: entries.length, unresolved });
  const keyRemedies = remediesByHost(solveRemedies);
  // Before any plan there is nothing to solve, build or run, and nothing the
  // line could say: the templates are in the empty conversation.
  const shown =
    phase !== "idle" ||
    entries.length > 0 ||
    landedPlan !== null ||
    installReview !== null ||
    solveRunning ||
    building !== null ||
    Boolean(error || notice) ||
    keyRemedies.length > 0 ||
    selectionRemedies.length > 0;
  if (!shown) return null;

  // The batch's controls: the line holds the one that is its main action, the
  // more part the others.
  const mainPart: BatchPart | null =
    main === "solve" ? "solve" : main === "stop-solve" ? "stop" : main === "run" ? "run" : null;
  const batchActions = (parts: readonly BatchPart[], inline: boolean) => (
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
      parts={parts}
      inline={inline}
    />
  );
  const otherParts = (["solve", "stop", "run"] as const).filter((part) => part !== mainPart);

  // What the closed more part holds that the line does not say: the plan's
  // failures, their reasons on the tooltip, or how the last session ended
  // when it left work undone (a finished one reads Ready). Open, the more
  // part says it itself.
  const reasons = distinctLines(solveErrors);
  const ending =
    !solveRunning && solveEndedBy && solveEndedBy !== "complete" ? sessionEndingText(solveEndedBy, unresolved) : "";
  const sign = moreOpen
    ? null
    : failed.length > 0
      ? { text: `${failed.length} failed: see more`, tooltip: reasons.join("\n") || undefined, failures: true }
      : ending
        ? { text: ending, tooltip: ending, failures: false }
        : null;

  return (
    <div className={styles.plan} role="group" aria-label={attachment.name}>
      <div className={styles.line}>
        <span className={styles.lineWords}>
          {activeBatchLabel && batchStartedAt !== null ? (
            <AgentRunStatusLine
              display={{ kind: "running", startedAt: batchStartedAt }}
              runningLabel={activeBatchLabel}
              runningDetail={batchDetailFor(entries, solveWave)}
              srLabel="Solve batch running"
            />
          ) : (
            <>
              <span className={styles.linePhase}>{words.phase}</span>
              {words.counts ? ` · ${words.counts}` : null}
            </>
          )}
        </span>
        {/* A polite live region that stays mounted, empty while there is
            nothing to say, so what comes into it is announced. */}
        <span
          className={`${styles.lineSign}${sign?.failures ? ` ${styles.lineSignFailed}` : ""}`}
          aria-live="polite"
          data-curio-plan-sign=""
          data-tooltip={sign?.tooltip}
        >
          {sign ? sign.text : null}
        </span>
        {userBlocked.length > 0 ? (
          <span className={styles.lineNeedsYou}>
            {userBlocked.length} need{userBlocked.length === 1 ? "s" : ""} you
          </span>
        ) : null}
        {mainPart ? batchActions([mainPart], true) : null}
        {main === "stop-build" ? (
          <button
            type="button"
            className={styles.run}
            disabled={buildStopping}
            data-tooltip="Stops the build after its current step. Everything already built stays."
            onClick={() => void stopBuild()}
          >
            {buildStopping ? "Stopping…" : "Stop"}
          </button>
        ) : null}
        {main === "resume" ? (
          <button
            type="button"
            className={styles.solve}
            data-tooltip={pauseReason ? `Paused: ${pauseReason.message}` : undefined}
            onClick={() => void simulate("auto")}
          >
            Resume
          </button>
        ) : null}
        <button
          type="button"
          className={styles.moreToggle}
          aria-expanded={moreOpen}
          aria-controls={moreOpen ? moreId : undefined}
          aria-label={moreOpen ? HIDE_PLAN_MORE : SHOW_PLAN_MORE}
          data-tooltip={moreOpen ? HIDE_PLAN_MORE : SHOW_PLAN_MORE}
          onClick={() => setMoreOpen((open) => !open)}
        >
          <FontAwesomeIcon icon={moreOpen ? faChevronUp : faChevronDown} />
        </button>
      </div>
      {/* What comes with a fix stays in view, whatever the more part shows. */}
      <SolveRemedies
        remedies={keyRemedies}
        selectionRemedies={selectionRemedies}
        onOpenChat={onOpenChat}
        agentNameOf={agentNameOf}
        nodeNameOf={nodeNameOf}
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
      {notice ? <div className={styles.hint}>{notice}</div> : null}
      {error ? (
        <div className={styles.error}>
          {error} <LlmConfigAction remedy={errorRemedy} />
        </div>
      ) : null}
      {moreOpen ? (
        <div id={moreId} className={styles.more}>
          {entries.length > 0 ? (
            <NodeRunPills
              entries={entries}
              userBlockedIds={userBlockedIds}
              solveWaiting={solveWaiting}
              // A node's own Solve waits for a batch, and for a build too.
              solveRunning={solveRunning || building !== null}
              nodeSolving={nodeSolving}
              onSolveNode={onSolveNode ? (nodeId) => void solveOne(nodeId) : undefined}
              agentNameOf={agentNameOf}
              nodeNameOf={nodeNameOf}
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
          <SolveFeedback reasons={reasons} notices={distinctLines(solveNotices)} />
          {landedPlan && onSimulate ? (
            <PlanBuildActions
              plan={landedPlan}
              paused={Boolean(pauseReason)}
              simBusy={building}
              // A paused build's Resume is the line's own action, and so is a
              // running build's Stop.
              withBuild={main !== "resume"}
              onSimulate={(mode) => void simulate(mode)}
            />
          ) : null}
          {batchActions(otherParts, false)}
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
          {paused && pauseReason ? (
            <div className={styles.hint}>Paused: {pauseReason.message} (Resume continues from here.)</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
