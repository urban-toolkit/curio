import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useFlowContext } from "../../../providers/FlowProvider";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import {
  attachmentDisplayName,
  sessionTokenTotals,
  type AgentAttachment,
  type AgentDatasetPick,
  type AgentDatasetSelection,
  type AgentRemedy,
  type AgentSessionTurn,
  type AgentSolveWave,
  type AgentRunStatus,
} from "../../../services/agents";
import { agentCategoryKey } from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import { AgentBuilderStrip } from "./AgentBuilderStrip";
import { NodeSolveRow } from "./NodeSolveRow";
import { TranscriptJumpButton } from "./TranscriptJumpButton";
import { useTranscriptAutoScroll } from "./useTranscriptAutoScroll";
import { useAutoGrowTextarea } from "./useAutoGrowTextarea";
import { usePackageInstallReview } from "./usePackageInstallReview";
// dev/84: genuine cross-feature reuse — agent package proposals apply through
// the SAME install review the Nodes Catalog drawer uses, never a duplicate.
import { InstallPermissionsDialog } from "../../packages/publishing/InstallPermissionsDialog";
import { AgentSessionTokenCounter } from "./AgentSessionTokenCounter";
import { modalStackDepth } from "../../ModalShell";
import styles from "./AgentChatPanel.module.css";
import { AgentTurn } from "./chat/AgentTurn";
import { ChatHeader } from "./chat/ChatHeader";
import { ClearConversationDialog } from "./chat/ClearConversationDialog";
import { Composer } from "./chat/Composer";
import { ConversationTitle } from "./chat/ConversationTitle";
import { IntentMessage } from "./chat/IntentMessage";
import { PendingReplyRow } from "./chat/PendingReplyRow";
import { SuggestedPromptsRow } from "./chat/SuggestedPromptsRow";
import { useConversationTitle } from "./chat/useConversationTitle";
import { suggestedPromptsOf, targetLabelFor, targetTooltipFor, turnMetaFor } from "./chat/chatPanelDerived";

/**
 * Chat panel for one attached agent, styled to the approved concept screens
 * (docs/08 anatomy + the docs/03 chat-feedback visual system).
 *
 * Per DEC-042 (dev/21) the opened agent view has ONE dark top header carrying
 * the master agent identity, the ‹ › agent-cycling arrows (walking all
 * attachments in the dataflow), the name of what it is attached to (its ids
 * are on that line's tooltip, see below), and Close — no Pin, and no
 * static "Agent Catalog" bar (that chrome is exclusive to the Agents Roster
 * drawer). Below the header: the
 * intent-as-first-message transcript and pill input, unchanged.
 *
 * Presentational: the transcript and intent live in AgentAttachmentsProvider
 * (server-persisted session, memo dev/20), so closing/reopening restores the
 * conversation. Closing never detaches the agent.
 */
export const AgentChatPanel: React.FC<{
  attachment: AgentAttachment;
  turns: AgentSessionTurn[];
  /**
   * Display name of what this agent is attached to, for the header.
   *
   * Resolved by the caller, which can see the canvas; omit it and the header
   * falls back to naming the target kind and id (#228).
   */
  targetName?: string | null;
  /** 1-based position among all attached agents (for the `idx / total` label). */
  index?: number;
  /** Total attached agents in the dataflow. */
  total?: number;
  /** Cycle to the previous/next attachment; omitted → that arrow is disabled. */
  onPrev?: () => void;
  onNext?: () => void;
  /**
   * At its resting transform (#295). False mounts the panel off-screen so the
   * slide has somewhere to come from, and flips back to false for the exit
   * while the panel stays mounted.
   */
  presented?: boolean;
  /** The exit slide finished; the owner may unmount the panel now. */
  onExitComplete?: () => void;
  /** True while the session history is loading from the server. */
  loadingHistory?: boolean;
  /** History-load failure message; `onRetryHistory` retries the fetch. */
  historyError?: string | null;
  onRetryHistory?: () => void;
  onSend: (message: string) => Promise<void>;
  onClose: () => void;
  /** Transient tool-activity lines for the in-flight send (memo dev/41). */
  toolActivity?: string[];
  /** This attachment's live run status (memo dev/80) — drives the status
   * strip and the per-attachment send disable. Pass null for "wired, idle"
   * (the send busy state then follows the provider, keyed per attachment);
   * omit entirely to fall back to the panel-local sending flag. Without it
   * the strip still derives a finished state from the last turn's execution
   * record. */
  runStatus?: AgentRunStatus | null;
  /** Opens the shared settings modal at the Attached-instance scope (memo
   * dev/42) — the labeled cog beneath the header (the docs/08 anatomy slot;
   * never in the DEC-042 header itself). Omitted → no cog. */
  /** Review-before-apply actions (memo dev/41); omitted → cards render inert. */
  /** Resolves with the apply result when the caller has one (dev/105 A3: the
   * package install review walks `followUpProposals` from it). */
  onApplyProposal?: (proposalId: string) => Promise<{ followUpProposals?: string[] } | void>;
  onDismissProposal?: (proposalId: string) => Promise<void>;
  /** dev/67-5: per-node plan review actions (Simulation Mode: create). */
  onApplyPlanNode?: (proposalId: string, ref: string) => Promise<void>;
  onSavePlanGoal?: (proposalId: string, ref: string, goal: string) => Promise<void>;
  /** dev/67-8: the connection review stage. */
  onApplyPlanEdges?: (proposalId: string, indices?: number[]) => Promise<void>;
  /** dev/71: per-row Solve/Run on the plan card. */
  onSolvePlanNode?: (ref: string) => Promise<void>;
  onRunPlanNode?: (ref: string) => Promise<void>;
  /** dev/67-9: the Simulation Mode driver + its narration. */
  onSimulate?: (mode: "step" | "auto") => Promise<unknown>;
  onCancelSimulate?: () => Promise<void>;
  simulationActivity?: string;
  /** dev/52 Solve (Dataflow Builder attachments only); omitted → no strip. */
  onSolve?: (nodeIds?: string[]) => Promise<unknown>;
  /** dev/63: the live batch's per-node status overlay (nodeId → status). */
  solveProgress?: Record<string, string>;
  /** dev/106: the live batch's per-node failure reasons (nodeId → text). */
  solveErrors?: Record<string, string>;
  /** dev/116: the live batch's per-node remedies (a missing connection key). */
  solveRemedies?: Record<string, import("../../../services/agents").AgentRemedy>;
  /** dev/131: the session's live pass / waiting summary / ending. */
  solveWaiting?: Array<{ nodeId: string; kind: string; reason?: string; attachmentId?: string | null }>;
  solveEndedBy?: string | null;
  solvePass?: number | null;
  /** dev/131: resolve ONE node through its own agent, from its pill. */
  onSolveOneNode?: (nodeId: string) => Promise<unknown>;
  /** dev/118: the live batch's current topological wave. */
  solveWave?: import("../../../services/agents").AgentSolveWave;
  /** dev/118: per-node notices that are not errors (pending/skipped reasons, written-not-executed). */
  solveNotices?: Record<string, string>;
  /** dev/63: cancel the running solve. */
  onCancelSolve?: () => Promise<void>;
  /** dev/115 (Amendment A2): the per-node Solve — offered when this agent is
   * attached to a node; runs the node's current code in the sandbox, fixes
   * errors, re-runs, and lands an executed review. Omitted → no row. */
  onSolveNode?: () => Promise<unknown>;
  /** dev/115: the running per-node Solve's narration. */
  solveNodeActivity?: string | null;
  /** dev/72: opens ANOTHER attachment's chat — the delegation entries' and
   * plan-row chips' icon-links route through this. Omitted → entries inert. */
  onOpenAgentChat?: (attachmentId: string) => void;
  /** dev/126: record the confirmed dataset selection for this attachment's
   * node (Dataset Finder on a node only). */
  onRecordDatasetSelection?: (
    picks: import("../../../services/agents").AgentDatasetPick[],
  ) => Promise<import("../../../services/agents").AgentDatasetSelection>;
  /** dev/132: the shared catalog import, for a candidate row the runtime
   * could not fetch — resolves with the imported dataset's id. */
  onImportDataset?: (
    file: File,
    discoverySource?: import("../../../services/datasetCatalog/datasetCatalogTypes").DatasetDiscoverySourceInput,
  ) => Promise<string | null>;
  /** dev/72: live-existence check for a delegation home (stale → no link). */
  delegateExists?: (attachmentId: string) => boolean;
  onSaveIntent?: (intent: string | null) => Promise<void>;
  /** Persist a manual conversation title (memo dev/25). Omitted → the header
   * title is a plain, non-editable label. */
  onSaveTitle?: (title: string) => Promise<void>;
  onClearConversation?: () => Promise<void>;
}> = ({
  attachment,
  turns,
  targetName = null,
  index = 1,
  total = 1,
  onPrev,
  onNext,
  presented = true,
  onExitComplete,
  loadingHistory = false,
  historyError = null,
  onRetryHistory,
  onSend,
  onClose,
  toolActivity = [],
  runStatus,
  onApplyProposal,
  onDismissProposal,
  onApplyPlanNode,
  onSavePlanGoal,
  onApplyPlanEdges,
  onSolvePlanNode,
  onRunPlanNode,
  onSimulate,
  onCancelSimulate,
  simulationActivity,
  onSolve,
  onSolveNode,
  solveNodeActivity = null,
  solveProgress,
  solveErrors,
  solveRemedies,
  solveWaiting,
  solveEndedBy,
  solvePass,
  onSolveOneNode,
  solveWave,
  solveNotices,
  onCancelSolve,
  onOpenAgentChat,
  onRecordDatasetSelection,
  onImportDataset,
  delegateExists,
  onSaveIntent,
  onSaveTitle,
  onClearConversation,
}) => {
  // A link the agent writes to another Curio page leaves this dataflow, so it
  // asks first when there is unsaved work, like every other way out of it.
  const navigate = useNavigate();
  const { projectDirty } = useFlowContext();
  const { leave, dialog: leaveDialog } = useLeaveGuard(Boolean(projectDirty), LEAVE_DATAFLOW);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  // The app's own dialog, not the browser's (#197).
  const [confirmingClear, setConfirmingClear] = useState(false);
  // Inline click-to-edit conversation title (memo dev/25).
  const title = useConversationTitle(attachment, onSaveTitle);
  // Follow-at-bottom auto-scroll (memo dev/75): new turns and streamed chunks
  // keep the view pinned only while the user is already at the bottom;
  // scrolling up detaches follow until they return or jump to latest. Opening
  // a chat (attachment switch, history hydrated) always lands at the newest
  // turn — this covers delegated-agent chats too (dev/72 reuses this panel).
  const {
    containerRef: messagesRef,
    atBottom,
    unreadCount,
    jumpToLatest,
    pinToLatest,
  } = useTranscriptAutoScroll({
    content: turns,
    resetKey: attachment.attachmentId,
    ready: !loadingHistory,
    // Turn count, not content: the pill's unread badge (dev/83) counts whole
    // landed messages — streamed chunk growth never increments it.
    itemCount: turns.length,
  });
  /** The last value this panel prefilled — so a prefill may replace a prior
   * prefill, but never a draft the user actually typed (memo dev/39). */
  const lastPrefill = useRef("");
  // Multiline composer (memo dev/77): one-row pill that grows with content up
  // to ~6 rows, then scrolls internally. Keyed on `input`, so prefills and the
  // post-send reset re-measure too.
  const { textareaRef: composerRef } = useAutoGrowTextarea({ value: input, maxHeightPx: 120 });
  // dev/84: package.install proposals apply THROUGH the package install
  // review dialog — beginReview's promise spans the whole dialog round-trip,
  // so the review card's busy/error handling covers it.
  const packageReview = usePackageInstallReview(onApplyProposal);

  // Per-reply execution status (memo dev/80, amended: the status rides each
  // agent message, not a global strip). The review chip derives from the
  // attachment's proposal mirrors — it self-clears on apply/dismiss — and
  // marks only the NEWEST reply.
  const pendingReview =
    attachment.activeProposal?.status === "pending" || attachment.planProposal?.status === "pending";
  const runInFlight = runStatus?.phase === "running";
  const lastAgentIdx = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) if (turns[i].role === "agent") return i;
    return -1;
  }, [turns]);
  const metaCtx = { turns, runStatus, runInFlight, lastAgentIdx, pendingReview };
  // The reply being generated appears in `turns` only from its first delta;
  // until then (tool rounds, the blocking fallback) a standalone pending row
  // at the transcript tail carries the live indicator.
  const streamingTurnVisible = runInFlight && turns[turns.length - 1]?.role === "agent";
  // Cumulative session tokens (the strip by the composer): persisted Actuals
  // plus the in-flight run's interim sums (dev/37: provider-reported only,
  // never an estimate).
  const sessionTokens = useMemo(
    () => sessionTokenTotals(turns, runInFlight ? runStatus?.liveUsage : null),
    [turns, runInFlight, runStatus?.liveUsage],
  );
  // Per-attachment send disable (dev/80): when the provider wires a status
  // (null = wired, idle) the busy state follows it, keyed by attachment — so
  // cycling agents mid-run no longer leaks the panel-local `sending` flag
  // into another chat. Unwired (tests, previews): the local flag governs.
  const sendBusy = runStatus === undefined ? sending : runInFlight;

  const suggested = useMemo(() => suggestedPromptsOf(turns), [turns]);

  // The primary prompt prefills the input, editable with send active — but a
  // user-typed draft always wins over any prefill.
  useEffect(() => {
    const primary = suggested?.primary ?? "";
    setInput((prev) => (prev === "" || prev === lastPrefill.current ? primary : prev));
    lastPrefill.current = primary;
  }, [suggested, attachment.attachmentId]);

  // Candidate-selection composition (dev/50): the two-lane card composes the
  // confirmation prompt through the same prefill rule — an explicit selection
  // updates a prefill, never a draft the user actually typed.
  const composePrompt = (prompt: string) => {
    setInput((prev) => (prev === "" || prev === lastPrefill.current ? prompt : prev));
    lastPrefill.current = prompt;
  };

  const tint = styles[`tint_${agentCategoryKey(attachment.category)}` as keyof typeof styles];

  // Escape dismisses the chat (close only — the attachment is untouched);
  // while renaming, Escape cancels the edit instead (handled on the input).
  useEffect(() => {
    // A no-op while the panel is sliding out (#295): it is still mounted, so
    // the listener is still attached, and closing something already closing
    // would restart the fallback timer against a panel nobody can see.
    if (!presented) return;
    const onKey = (e: KeyboardEvent) => {
      // An open modal owns Escape. API Settings and agent import are raised
      // over this panel, and this listener is on window in the bubble phase,
      // so the modal cannot stop it firing. It has to stand down itself, or
      // dismissing the dialog closed the chat behind it as well.
      if (modalStackDepth() > 0) return;
      if (e.key === "Escape" && !title.editing) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, title.editing, presented]);

  // The exit settles on the PANEL's own transform and nothing else. This panel
  // is full of inner transitions (bubbles, chips, the run status line), and
  // every one of them bubbles a transitionend to this element - so an
  // unguarded handler unmounted the panel the moment any child finished
  // animating, mid-slide.
  const panelRef = useRef<HTMLDivElement | null>(null);
  const handlePanelTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== panelRef.current || e.propertyName !== "transform") return;
      if (presented) return;
      onExitComplete?.();
    },
    [onExitComplete, presented],
  );

  const send = async () => {
    const message = input.trim();
    if (!message || sendBusy) return;
    setInput("");
    // Sending is explicit bottom engagement: the user always sees their own
    // message land and the reply start, even if they had scrolled up.
    pinToLatest();
    setSending(true);
    try {
      await onSend(message);
    } finally {
      setSending(false);
    }
  };

  const displayName = attachmentDisplayName({ name: attachment.name, title: title.displayedTitle ?? null });
  const turnActions = {
    onComposePrompt: composePrompt,
    onInternalLink: (to: string) => leave(() => navigate(to)),
    onOpenAgentChat,
    delegateExists,
    onRecordDatasetSelection,
    onImportDataset,
    onApplyProposal,
    beginPackageReview: packageReview.beginReview,
    onDismissProposal,
    onApplyPlanNode,
    onSavePlanGoal,
    onApplyPlanEdges,
    onSolvePlanNode,
    onRunPlanNode,
  };

  return (
    <div
      ref={panelRef}
      className={`${styles.panel} ${presented ? styles.panelPresented : ""}`}
      onTransitionEnd={handlePanelTransitionEnd}
      role="dialog"
      aria-label={`Chat with ${displayName}`}
      aria-hidden={!presented}
    >
      <ChatHeader
        tint={tint}
        title={
          <ConversationTitle agentName={attachment.name} displayName={displayName} editable={Boolean(onSaveTitle)} title={title} />
        }
        index={index}
        total={total}
        onPrev={onPrev}
        onNext={onNext}
        onClear={onClearConversation ? () => setConfirmingClear(true) : undefined}
        onClose={onClose}
        targetLabel={targetLabelFor(attachment, targetName)}
        targetTooltip={targetTooltipFor(attachment)}
        titleError={title.error}
      />

      {/* The dev/52 builder strip: Dataflow Builder attachments only — every
          other agent's chat is pixel-identical. */}
      {onSolveNode && attachment.target.kind === "node" ? (
        <NodeSolveRow
          onSolveNode={onSolveNode}
          onOpenChat={onOpenAgentChat}
          activity={solveNodeActivity}
          live={attachment.liveJob?.status === "running" && attachment.liveJob.kind === "solve-node"}
        />
      ) : null}
      {onSolve && attachment.coord.startsWith("agent.dataflow-builder@") ? (
        <AgentBuilderStrip
          attachment={attachment}
          onSolve={onSolve}
          solveProgress={solveProgress}
          solveErrors={solveErrors}
          solveRemedies={solveRemedies}
          onOpenChat={onOpenAgentChat}
          solveWaiting={solveWaiting}
          solveEndedBy={solveEndedBy}
          solvePass={solvePass}
          onSolveNode={onSolveOneNode}
          solveWave={solveWave}
          solveNotices={solveNotices}
          onCancelSolve={onCancelSolve}
          onComposePrompt={composePrompt}
          onApplyProposal={onApplyProposal}
          onDismissProposal={onDismissProposal}
          onSimulate={onSimulate}
          onCancelSimulate={onCancelSimulate}
          simulationActivity={simulationActivity}
        />
      ) : null}

      {/* position:relative wrapper so the Jump-to-latest pill overlays the
          scroll area without shifting layout (absolute inside the scroller
          would scroll away with the content). */}
      <div className={styles.messagesWrap}>
      <div className={styles.messages} ref={messagesRef} tabIndex={-1}>
        <IntentMessage intent={attachment.intent} onSaveIntent={onSaveIntent} />
        {historyError ? (
          <div className={`${styles.systemLine} ${styles.systemError}`}>
            {historyError}
            {onRetryHistory ? (
              <button type="button" className={styles.retry} onClick={onRetryHistory}>
                Retry
              </button>
            ) : null}
          </div>
        ) : null}
        {loadingHistory ? (
          <div className={styles.systemLine}>Loading conversation…</div>
        ) : turns.length === 0 && !historyError ? (
          <div className={styles.systemLine}>Ask this agent something to get started.</div>
        ) : (
          turns.map((t, i) =>
            t.role === "user" ? (
              <div key={i} className={styles.msgUser}>
                {t.text}
              </div>
            ) : (
              <AgentTurn key={i} turn={t} attachment={attachment} tint={tint} meta={turnMetaFor(t, i, metaCtx)} actions={turnActions} />
            ),
          )
        )}
        {toolActivity.map((line, i) => (
          <div key={`tool-${i}`} className={styles.systemLine}>
            {line}
          </div>
        ))}
        {runInFlight && !streamingTurnVisible && runStatus ? (
          <PendingReplyRow tint={tint} startedAt={runStatus.startedAt} />
        ) : null}
      </div>
      <TranscriptJumpButton
        visible={!atBottom}
        onJump={jumpToLatest}
        count={unreadCount}
        focusFallbackRef={messagesRef}
      />
      {/* dev/84: the reviewed package install — the dialog's Install button
          is what fires the proposal apply; Cancel keeps it pending. */}
      {packageReview.candidate ? (
        <InstallPermissionsDialog
          pkg={packageReview.candidate.pkg}
          conflicts={packageReview.candidate.conflicts}
          busy={packageReview.busy}
          onCancel={packageReview.cancel}
          onConfirm={() => void packageReview.confirm()}
        />
      ) : null}
      {confirmingClear ? (
        <ClearConversationDialog
          onConfirm={() => {
            setConfirmingClear(false);
            void onClearConversation?.();
          }}
          onCancel={() => setConfirmingClear(false)}
        />
      ) : null}
      </div>

      {suggested && suggested.alternatives.length > 0 ? (
        <SuggestedPromptsRow alternatives={suggested.alternatives} onPick={setInput} />
      ) : null}

      {/* Cumulative counter strip (memo dev/80, amended): the per-reply
          status lives on each agent message; this strip — outside the
          scroller, directly above the composer — carries only the session's
          accumulated token total, right-aligned near the input. Hidden while
          history hydrates and while nothing was ever reported. */}
      {!loadingHistory && sessionTokens ? (
        <div className={styles.statusStrip}>
          <span className={styles.statusStripSpacer} />
          <AgentSessionTokenCounter totals={sessionTokens} live={runInFlight} />
        </div>
      ) : null}

      <Composer value={input} onChange={setInput} onSend={() => void send()} busy={sendBusy} textareaRef={composerRef} />
      {leaveDialog}
    </div>
  );
};
