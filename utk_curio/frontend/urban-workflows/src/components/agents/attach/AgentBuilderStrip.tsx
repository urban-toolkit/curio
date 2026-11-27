import React, { useEffect, useState } from "react";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faChevronUp } from "@fortawesome/free-solid-svg-icons";
import { ROW_SOLVE_RUNNING_HINT, buildRunningOn } from "../../../services/agents/planBuild";
import type { AgentAttachment, AgentRemedy, AgentSolveWave } from "../../../services/agents";
import { LlmConfigAction, remedyOf } from "../../llmConfigs/LlmConfigAction";
import { useFlowContext } from "../../../providers/FlowProvider";
import { nodeLabel } from "../../scenarios/scenarioLabels";
import { useRunTicker } from "./useRunTicker";
import styles from "./AgentBuilderStrip.module.css";
import { MissingSpecialistReview } from "./builderStrip/MissingSpecialistReview";
import { SolveRemedies } from "./builderStrip/SolveFeedback";
import { useMenuPopup } from "./chat/useMenuPopup";
import {
  AT_WORK_RUNS,
  AT_WORK_WORDS,
  BUILT_RUNS,
  BUILT_STATES,
  builtCount,
  inPlanOrder,
  mainActionOf,
  passLineText,
  planLeftToBuild,
  planLineWords,
  plural,
  remediesByHost,
  waveWords,
  type PauseView,
} from "./builderStrip/builderStripDerived";

/** The line's menu of the plan's other actions, by what it holds. */
export const PLAN_ACTIONS = "More plan actions";

/** What the line's actions do, on their tooltips. */
export const SOLVE_HINT = "Builds every node: each runs in the sandbox, is fixed, and lands only once it ran";
export const RETRY_FAILED_HINT = "Solves the nodes that failed again: each runs in the sandbox, is fixed, and lands only once it ran";
export const RETRY_INTERRUPTED_HINT =
  "Solve was interrupted: the server stopped while it was running. Finished nodes kept their content; nothing was " +
  "replayed. Retry continues from what is still pending.";
export const STOP_SOLVE_HINT =
  "Ends the session after the current node finishes (a running fetch cannot be aborted). Everything already written " +
  "stays. Solve keeps running if you close this chat.";
export const STOP_BUILD_HINT =
  "Stops the build after its current step. Everything built stays. The build goes on if you close this chat.";
export const SHOW_SOURCES_HINT = "Goes to its sources in this chat. Your pick builds it, and the plan goes on.";
export const RESUME_HINT = "Goes on with the build, in plan order, from where it paused";
export const RUN_HINT = "Runs every node of the dataflow";

/** What the menu's two builds do, under their names. */
export const BUILD_PLAN_SAYS = "In plan order, each node's code lands as it passes; the first failure pauses.";
export const STEP_SAYS = "Builds the next node only.";

/** The ledger states of a node that waits for its source, by what it waits on. */
const WAIT_OF_STATE: Record<string, PauseView["kind"]> = {
  "awaiting-source": "pick",
  "awaiting-download": "download",
  "awaiting-install": "install",
};

/** The running line: the dot, what runs and on which node, the time it has
 *  run, and how many of the plan's nodes are built. */
const PlanRunLine: React.FC<{
  label: string;
  subject: string | null;
  detail: string;
  startedAt: number;
  tooltip?: string;
  srLabel: string;
}> = ({ label, subject, detail, startedAt, tooltip, srLabel }) => {
  const { elapsedLabel } = useRunTicker(startedAt);
  return (
    <span className={styles.runLine} role="status" aria-live="polite" data-tooltip={tooltip}>
      <span className={styles.srOnly}>{srLabel}</span>
      <span className={styles.runDot} aria-hidden="true" />
      <span aria-hidden="true">
        <span className={styles.linePhase}>{label}</span>
        {subject ? ` ${subject}` : null}
        <span className={styles.lineMuted}>{` · ${elapsedLabel} · ${detail}`}</span>
      </span>
    </span>
  );
};

/**
 * The plan line of an agent that declares dataflow.orchestrate (dev/52 DR-5),
 * under the chat's Goal line. Everything derives from the server-owned
 * `builderSession` (DR-2).
 *
 * The line says where the plan stands in one count: Planned, Ready, and while
 * a batch or a build runs, the node at work, the time it has run and how many
 * nodes are built. A pause or a failure names its node. It holds one action:
 * Solve (or Retry), Stop while a batch or a build runs, Show its sources while
 * a node waits for the person's pick of its source (the pick goes on by
 * itself), Resume when a build paused on anything else, Run workflow once the
 * plan is ready. Beside it, a menu holds Build & validate plan and Step while
 * a landed plan has nodes left to build and nothing runs. Each node's own
 * state, its Solve and Run, are on its row of the plan's card. What comes with
 * a fix stays in view under the line: a missing key's Add key, a missing
 * specialist's Add to project, an action's error with its Open API Settings.
 * Before any plan there is no line: the planning templates are in the empty
 * conversation.
 */
export const AgentBuilderStrip: React.FC<{
  attachment: AgentAttachment;
  onSolve: (nodeIds?: string[]) => Promise<unknown>;
  /** dev/63: the live batch's transient per-node statuses (nodeId → status,
   * including "solving"), over the persisted nodeRuns. */
  solveProgress?: Record<string, string>;
  /** dev/106: the live batch's per-node failure reasons (nodeId → text): the
   * line's tooltip, and each on its node's row of the plan's card. */
  solveErrors?: Record<string, string>;
  /** dev/116: the live batch's per-node remedies: an Add key per host. */
  solveRemedies?: Record<string, AgentRemedy>;
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
  /** dev/118: the live batch's current wave. */
  solveWave?: AgentSolveWave;
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
  /** dev/67-9: the running build's narration: the line's tooltip. */
  simulationActivity?: string;
  /** The build the chat runs for this agent, step or auto, which outlives
   *  this line: drawn again (the chat opened again, or the rail back on this
   *  agent), the line still shows it and its Stop. A build another tab runs,
   *  which the listing names, holds the line the same way
   *  (`buildRunningOn`). */
  simulating?: "step" | "auto" | null;
  /** Brings the card of *nodeId*'s sources into view: in this chat, else in
   *  its Dataset Finder's. */
  onShowSources?: (nodeId: string) => void;
  /** The viewer shows run details: the batch's pass and wave. */
  runDetails?: boolean;
}> = ({
  attachment,
  onSolve,
  solveProgress,
  solveErrors,
  solveRemedies,
  solveWaiting,
  solveEndedBy,
  solvePass,
  solveWave,
  onCancelSolve,
  onApplyProposal,
  onDismissProposal,
  onSimulate,
  onCancelSimulate,
  simulationActivity,
  simulating = null,
  onShowSources,
  runDetails = false,
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
  // A build this line started, one the chat still runs for this agent, or one
  // the server says runs (another tab's among them).
  const building = simBusy ?? buildRunningOn(attachment, simulating);
  // A row's Solve of the plan runs on the server, the one a pick goes on with
  // among them: no build or Step starts over it.
  const rowSolveRunning = Boolean(attachment.validating);
  // Its Stop was asked for: the build stops after its current step.
  const [buildStopping, setBuildStopping] = useState(false);
  // This line's build was stopped: the line says so until a build runs again.
  const [buildStopped, setBuildStopped] = useState(false);
  useEffect(() => {
    if (!building) setBuildStopping(false);
    else setBuildStopped(false);
  }, [building]);
  const [error, setError] = useState<string | null>(null);
  // The refusal's remedy, when it has one (no LLM configuration answers a
  // delegate this run relies on).
  const [errorRemedy, setErrorRemedy] = useState<AgentRemedy | null>(null);
  const menu = useMenuPopup();
  // When the line first saw what runs now: its clock.
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);

  const session = attachment.builderSession ?? { phase: "idle" as const };
  const phase = session.phase ?? "idle";
  const nodeRuns = session.nodeRuns ?? {};
  const nodeStates = session.nodeStates ?? {};
  const liveJob = attachment.liveJob?.status === "running" ? attachment.liveJob : null;
  const solveRunning = solving || phase === "solving" || liveJob?.kind === "solve-batch";

  // The plan's nodes, in its order, each with its ref; then nodes the batch
  // runs that the plan does not list, an earlier plan's.
  const plan = attachment.planProposal ?? null;
  const refs = plan?.tool === "dataflow.plan.write" ? plan.appliedRefs ?? [] : [];
  const refOf: Record<string, string> = {};
  for (const ref of refs) {
    const id = plan?.nodeIds?.[ref] ?? session.nodeIds?.[ref];
    if (id) refOf[id] = ref;
  }
  const runs: Record<string, string> = { ...nodeRuns, ...(solveProgress ?? {}) };
  const canvasIds = flowNodes.map((node) => node.id);
  const ids = inPlanOrder(
    [...new Set([...Object.keys(refOf), ...Object.keys(runs)])].map((id) => [id, null] as [string, null]),
    plan,
    canvasIds,
  ).map(([id]) => id);
  const stateOf = (id: string) => (refOf[id] ? nodeStates[refOf[id]] : undefined);
  const isBuilt = (id: string) => BUILT_STATES.has(stateOf(id) ?? "") || BUILT_RUNS.has(runs[id] ?? "");
  const built = ids.filter(isBuilt).length;
  const left = ids.length - built;
  const failed = ids.filter((id) => !isBuilt(id) && (runs[id] === "failed" || stateOf(id) === "failed"));
  const pending = ids.filter((id) => runs[id] === "pending");

  // The nodes that wait for the person's pick of their source: those the
  // running Solve says, those the listing says this agent waits on, and the
  // plan's nodes its ledger keeps waiting for a pick.
  const waitsForPick = new Set([
    ...(solveWaiting ?? []).filter((w) => w.kind === "dataset-selection").map((w) => w.nodeId),
    ...Object.entries(solveRemedies ?? {})
      .filter(([, remedy]) => remedy?.kind === "dataset-selection")
      .map(([id]) => id),
    ...(attachment.waitsForYou ?? []),
    ...ids.filter((id) => stateOf(id) === "awaiting-source"),
  ]);
  const pickIds = ids.filter((id) => waitsForPick.has(id)).concat([...waitsForPick].filter((id) => !ids.includes(id)));

  // The plan that landed, while any of its nodes is left to build: Build &
  // validate and Step work on it.
  const landedPlan = planLeftToBuild(plan, session) ? plan : null;
  const pauseReason = !building ? session.pauseReason ?? null : null;
  // Why the build paused, as the line names it; a wait for a pick is the
  // line's own (`pickIds`).
  const pause: PauseView | null = (() => {
    if (!pauseReason) return null;
    const pausedIds = [
      ...(pauseReason.nodes ?? []).map((n) => n.nodeId ?? (n.ref ? plan?.nodeIds?.[n.ref] : undefined)),
      pauseReason.ref ? plan?.nodeIds?.[pauseReason.ref] ?? session.nodeIds?.[pauseReason.ref] : undefined,
    ].filter((id): id is string => Boolean(id));
    if (pauseReason.kind === "validation-failed") {
      return { kind: "failed", names: pausedIds.map(nodeNameOf) };
    }
    if (pauseReason.kind === "awaiting-source") {
      const waits = pausedIds.map((id) => WAIT_OF_STATE[stateOf(id) ?? ""] ?? "pick");
      const kind = waits.includes("download") ? "download" : waits.includes("install") ? "install" : "pick";
      return { kind, names: pausedIds.filter((_, i) => waits[i] === kind).map(nodeNameOf) };
    }
    return { kind: "other", names: [], message: pauseReason.message };
  })();

  const running = solveRunning || building !== null;
  // The plan waits on the person when every node left to build waits for its
  // pick, or for a node upstream of it that does, as a build that paused on a
  // pick says by pausing: then the line's action goes to the card; else Solve
  // goes on with the others.
  const waitsUpstream = new Set((solveWaiting ?? []).filter((w) => w.kind === "upstream").map((w) => w.nodeId));
  const pickBlocksAll =
    pickIds.length > 0 &&
    (pauseReason?.kind === "awaiting-source" ||
      ids.filter((id) => !isBuilt(id)).every((id) => waitsForPick.has(id) || waitsUpstream.has(id)));
  const words = planLineWords({
    phase,
    waitingForPick: running ? [] : pickIds.map(nodeNameOf),
    pickBlocksAll,
    pause: pause && pause.kind !== "pick" ? pause : null,
    failed: running ? [] : failed.map(nodeNameOf),
    ended: !solveRunning && solveEndedBy && solveEndedBy !== "complete" ? solveEndedBy : null,
    buildStopped,
    nodes: ids.length,
    left,
  });
  const main = mainActionOf({
    solveRunning,
    canStopSolve: Boolean(onCancelSolve),
    building: building !== null,
    canStopBuild: Boolean(onCancelSimulate),
    waitsForPick: pickBlocksAll,
    paused: Boolean(pauseReason && landedPlan && onSimulate),
    phase,
  });

  // The running line's clock: from when this line first saw the run; a run
  // of another kind starts it again.
  const runKind = solveRunning ? "solve" : building ? "build" : null;
  useEffect(() => {
    setRunStartedAt(runKind ? Date.now() : null);
  }, [runKind]);
  // A batch's Stop reads Stopping… until that batch ends, however it ends.
  useEffect(() => {
    if (!solveRunning) setCancelling(false);
  }, [solveRunning]);

  const solve = async (nodeIds?: string[]) => {
    setSolving(true);
    setError(null);
    setErrorRemedy(null);
    try {
      await onSolve(nodeIds);
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

  const simulate = async (mode: "step" | "auto") => {
    if (!onSimulate || building || rowSolveRunning) return;
    setSimBusy(mode);
    setError(null);
    setErrorRemedy(null);
    try {
      const done = (await onSimulate(mode)) as { status?: string } | undefined;
      if (done?.status === "cancelled") setBuildStopped(true);
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

  // dev/106: the missing-specialist review, from the mirror.
  const installReview =
    attachment.activeProposal &&
    attachment.activeProposal.tool === "project.install" &&
    attachment.activeProposal.status === "pending"
      ? attachment.activeProposal
      : null;
  const keyRemedies = remediesByHost(solveRemedies);
  // Before any plan there is nothing to solve, build or run, and nothing the
  // line could say: the templates are in the empty conversation.
  const shown =
    phase !== "idle" ||
    ids.length > 0 ||
    landedPlan !== null ||
    installReview !== null ||
    running ||
    Boolean(error) ||
    keyRemedies.length > 0;
  if (!shown) return null;

  // The line's menu: the builds that can run now, never while one runs.
  const menuItems: Array<{ mode: "auto" | "step"; name: string; says: string }> =
    landedPlan && onSimulate && !running && !rowSolveRunning
      ? [
          ...(main === "resume" ? [] : [{ mode: "auto" as const, name: "Build & validate plan", says: BUILD_PLAN_SAYS }]),
          { mode: "step" as const, name: "Step", says: STEP_SAYS },
        ]
      : [];

  // What runs, on which node, for the running line.
  const atWork = solveRunning
    ? ids.filter((id) => AT_WORK_RUNS.has(runs[id] ?? ""))
    : building && session.currentRef
      ? [plan?.nodeIds?.[session.currentRef] ?? session.nodeIds?.[session.currentRef]].filter((id): id is string => Boolean(id))
      : [];
  const atWorkSubject = atWork.length === 1 ? nodeNameOf(atWork[0]) : atWork.length > 1 ? plural(atWork.length, "node") : null;
  const atWorkTooltip =
    atWork.length === 1
      ? building
        ? simulationActivity
          ? `${nodeNameOf(atWork[0])}: ${simulationActivity}`
          : undefined
        : AT_WORK_WORDS[runs[atWork[0]] ?? ""]
          ? `${nodeNameOf(atWork[0])}: ${AT_WORK_WORDS[runs[atWork[0]] ?? ""]}`
          : undefined
      : building
        ? simulationActivity
        : undefined;
  const pickWords =
    solveRunning && pickIds.length > 0
      ? ` · ${pickIds.length === 1 ? `${nodeNameOf(pickIds[0])} needs a source` : `${plural(pickIds.length, "node")} need a source`}`
      : "";
  // The line's tooltip: why a build paused, in the server's words, else the
  // failures' reasons; each is on its node's row of the card too.
  const reasons = pauseReason
    ? [pauseReason.message]
    : Array.from(new Set(failed.map((id) => solveErrors?.[id]).filter((r): r is string => Boolean(r))));

  const solveLabel =
    phase === "interrupted"
      ? `Retry ${left} interrupted`
      : failed.length && !pending.length
        ? `Retry ${failed.length} failed`
        : "Solve";
  const solveHint =
    phase === "interrupted" ? RETRY_INTERRUPTED_HINT : failed.length && !pending.length ? RETRY_FAILED_HINT : SOLVE_HINT;

  return (
    <div className={styles.plan} role="group" aria-label={attachment.name}>
      <div className={styles.line}>
        {running && runStartedAt !== null ? (
          <span className={styles.lineWords}>
            <PlanRunLine
              label={building === "step" ? "Stepping" : building ? "Building" : "Solving"}
              subject={atWorkSubject}
              detail={builtCount(built, ids.length) + pickWords}
              startedAt={runStartedAt}
              tooltip={atWorkTooltip}
              srLabel={building ? "Build running" : "Solve batch running"}
            />
          </span>
        ) : (
          // A polite live region: what comes into it, a failure or a pause, is
          // announced.
          <span
            className={styles.lineWords}
            aria-live="polite"
            data-curio-plan-words=""
            data-tooltip={reasons.length ? reasons.join("\n") : undefined}
          >
            <span className={styles.linePhase}>{words.phase}</span>
            {words.muted ? <span className={styles.lineMuted}>{` · ${words.muted}`}</span> : null}
            {words.subject || words.predicate ? <span className={styles.lineMuted}>{" · "}</span> : null}
            {words.subject ? <span>{words.subject}</span> : null}
            {words.predicate ? (
              <span className={words.tone === "fail" ? styles.lineFail : words.tone === "warn" ? styles.lineWarn : undefined}>
                {words.subject ? ` ${words.predicate}` : words.predicate}
              </span>
            ) : null}
            {words.waits ? (
              <>
                <span className={styles.lineMuted}>{" · "}</span>
                <span className={styles.lineWarn}>{words.waits}</span>
              </>
            ) : null}
          </span>
        )}
        {main === "solve" ? (
          <button
            type="button"
            className={styles.solve}
            disabled={solveRunning}
            data-tooltip={solveHint}
            onClick={() => void solve(failed.length && !pending.length ? failed : undefined)}
          >
            {solveRunning ? "Solving…" : solveLabel}
          </button>
        ) : null}
        {main === "stop-solve" ? (
          <button
            type="button"
            className={styles.run}
            disabled={cancelling}
            data-tooltip={STOP_SOLVE_HINT}
            onClick={() => void cancel()}
          >
            {cancelling ? "Stopping…" : "Stop"}
          </button>
        ) : null}
        {main === "stop-build" ? (
          <button
            type="button"
            className={styles.run}
            disabled={buildStopping}
            data-tooltip={STOP_BUILD_HINT}
            onClick={() => void stopBuild()}
          >
            {buildStopping ? "Stopping…" : "Stop"}
          </button>
        ) : null}
        {main === "show-sources" ? (
          <button
            type="button"
            className={styles.solve}
            data-tooltip={SHOW_SOURCES_HINT}
            disabled={!onShowSources}
            onClick={() => onShowSources?.(pickIds[0])}
          >
            Show its sources
          </button>
        ) : null}
        {main === "resume" ? (
          <button
            type="button"
            className={styles.solve}
            disabled={rowSolveRunning}
            data-tooltip={rowSolveRunning ? ROW_SOLVE_RUNNING_HINT : RESUME_HINT}
            onClick={() => void simulate("auto")}
          >
            Resume
          </button>
        ) : null}
        {main === "run" ? (
          <button
            type="button"
            className={styles.solve}
            disabled={isRunActive}
            data-tooltip={isRunActive ? "A run is already in progress" : RUN_HINT}
            onClick={() => playAllNodes()}
          >
            Run workflow
          </button>
        ) : null}
        {menuItems.length > 0 ? (
          <span className={styles.menuWrap}>
            <button
              ref={(el) => {
                menu.anchorRef.current = el;
              }}
              type="button"
              className={clsx(styles.moreToggle, menu.open !== null && styles.moreToggleOpen)}
              aria-label={PLAN_ACTIONS}
              aria-haspopup="menu"
              aria-expanded={menu.open !== null}
              data-tooltip={PLAN_ACTIONS}
              onClick={() => menu.toggle(true)}
            >
              <FontAwesomeIcon icon={menu.open !== null ? faChevronUp : faChevronDown} />
            </button>
            {menu.open !== null ? (
              <div
                ref={menu.menuRef}
                className={styles.menu}
                role="menu"
                aria-label={PLAN_ACTIONS}
                onKeyDown={menu.onMenuKeyDown}
              >
                {menuItems.map((item) => (
                  <button
                    key={item.mode}
                    type="button"
                    role="menuitem"
                    className={styles.menuItem}
                    onClick={() => {
                      menu.close();
                      void simulate(item.mode);
                    }}
                  >
                    {item.name}
                    <span className={styles.menuItemSays}>{item.says}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </span>
        ) : null}
      </div>
      {/* What comes with a fix stays in view. */}
      <SolveRemedies remedies={keyRemedies} />
      {installReview && (onApplyProposal || onDismissProposal) ? (
        <MissingSpecialistReview
          review={installReview}
          reviewBusy={reviewBusy}
          solving={solving}
          onApply={onApplyProposal ? () => void review(onApplyProposal, installReview.proposalId) : undefined}
          onDismiss={onDismissProposal ? () => void review(onDismissProposal, installReview.proposalId) : undefined}
        />
      ) : null}
      {error ? (
        <div className={styles.error}>
          {error} <LlmConfigAction remedy={errorRemedy} />
        </div>
      ) : null}
      {runDetails && solveRunning && ((solvePass ?? 0) > 0 || waveWords(solveWave)) ? (
        <div className={styles.hint} data-curio-run-details="">
          {[
            (solvePass ?? 0) > 0 ? passLineText(solvePass as number, left, pickIds.length) : null,
            waveWords(solveWave),
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
      ) : null}
    </div>
  );
};
