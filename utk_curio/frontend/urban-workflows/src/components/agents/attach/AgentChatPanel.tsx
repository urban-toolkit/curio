import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useFlowContext } from "../../../providers/FlowProvider";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import {
  attachmentDisplayName,
  declaresCapability,
  landsAsAChange,
  ORCHESTRATE_CAPABILITY,
  sessionTokenTotals,
  writtenBySomeoneElse,
  type AgentAttachment,
  type AgentSessionTurn,
  type AgentRunStatus,
  type RunSkill,
} from "../../../services/agents";
import { agentCategoryKey } from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import { AgentBuilderStrip } from "./AgentBuilderStrip";
import { workingText } from "./AgentAvatarBadge";
import { NodeSolveRow } from "./NodeSolveRow";
import { TranscriptJumpButton } from "./TranscriptJumpButton";
import { useTranscriptAutoScroll } from "./useTranscriptAutoScroll";
import { useAutoGrowTextarea } from "./useAutoGrowTextarea";
import { usePackageInstallReview } from "./usePackageInstallReview";
// dev/84: genuine cross-feature reuse: agent package proposals apply through
// the SAME install review the Nodes Catalog drawer uses, never a duplicate.
import { InstallPermissionsModal } from "../../packages/publishing/InstallPermissionsDialog";
import { escapeAnswered, modalStackDepth } from "../../ModalShell";
import styles from "./AgentChatPanel.module.css";
import { PlanningTemplates } from "./builderStrip/PlanningTemplates";
import { AgentRail } from "./chat/AgentRail";
import { AgentTurn } from "./chat/AgentTurn";
import { ChatHeader } from "./chat/ChatHeader";
import { ClearConversationDialog } from "./chat/ClearConversationDialog";
import { Composer } from "./chat/Composer";
import { ConversationTitle } from "./chat/ConversationTitle";
import { GoalLine } from "./chat/GoalLine";
import { IntentMessage } from "./chat/IntentMessage";
import { PendingReplyRow } from "./chat/PendingReplyRow";
import { SuggestedPromptsRow } from "./chat/SuggestedPromptsRow";
import { useConversationTitle } from "./chat/useConversationTitle";
import { useGoalLine } from "./chat/useGoalLine";
import { WaitingAskRow } from "./chat/WaitingAskRow";
import {
  canvasUnchangedFor,
  suggestedPromptsOf,
  targetPhraseFor,
  targetTooltipFor,
  turnMetaFor,
} from "./chat/chatPanelDerived";
import type { WaitingAsk } from "../../../providers/agents/turnAsks";

/**
 * Chat panel for one attached agent, styled to the approved concept screens
 * (docs/08 anatomy + the docs/03 chat-feedback visual system). It opens under
 * the top bar, on the window's right.
 *
 * Down its left side, the agents rail: every agent on the dataflow, the open
 * one marked, and a click opens another's chat. Beside it, per DEC-042
 * (dev/21), ONE dark header row: the agent's glyph, the conversation's title,
 * what it is attached to (its ids on that line's tooltip), More (Rename
 * conversation, Clear conversation, Tokens used) and Close; no Pin, and no
 * static "Agent Catalog" bar (that chrome is exclusive to the Agents Roster
 * drawer). Under the header: the dataflow's goal (`GoalLine`), the same in
 * every agent's chat; the plan line of an agent that solves a dataflow, or
 * Solve this node in a node agent's; then the intent-as-first-message
 * transcript and the pill composer.
 *
 * Presentational: the transcript and intent live in AgentAttachmentsProvider
 * (server-persisted session, memo dev/20), so closing/reopening restores the
 * conversation. Closing never detaches the agent.
 */
export const AgentChatPanel: React.FC<{
  attachment: AgentAttachment;
  turns: AgentSessionTurn[];
  /** The viewer's account. The owner and the editors the owner invited share
   * the chat, and a message someone else wrote names its writer. */
  viewerAccount?: string | null;
  /** An invited editor's chat: an install a proposal makes waits for the
   * owner's review in place of its Apply and Dismiss. */
  installsWaitForOwner?: boolean;
  /**
   * Display name of what this agent is attached to, for the header: a node's
   * name, or "from A to B" for a connection.
   *
   * Resolved by the caller, which can see the canvas; omit it and the header
   * falls back to naming the target kind and id (#228).
   */
  targetName?: string | null;
  /** Every agent on the dataflow, in the attachments' order, for the rail;
   *  a click on one opens its chat through `onOpenAgentChat`. Omitted → no
   *  rail. */
  attachments?: AgentAttachment[];
  /** What each of *attachments* is attached to, named as `targetName` is;
   *  omitted, only the open agent's target is named. */
  targetNameOf?: (attachment: AgentAttachment) => string | null;
  /** What each agent at work is doing, for its running dot on the rail: in
   *  the dataflow's room, or solving in the background. Omitted → a running
   *  job alone. */
  workingOf?: (attachment: AgentAttachment) => string | null;
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
   * strip. Pass null for "wired, idle": the provider then follows each
   * attachment's asks, and a running turn never holds the composer back, as
   * an ask sent meanwhile waits its turn; omit entirely to fall back to the
   * panel-local sending flag. Without it the strip still derives a finished
   * state from the last turn's execution record. */
  runStatus?: AgentRunStatus | null;
  /** The asks waiting their turn after the running one, in order. */
  waitingAsks?: WaitingAsk[];
  /** Stop the running turn: whoever asked it, the owner or an editor may.
   * Omitted → no Stop. */
  onStopTurn?: () => Promise<void>;
  /** Withdraw a waiting ask the viewer asked. Omitted → no Withdraw. */
  onWithdrawAsk?: (askId: string) => Promise<void>;
  /** An install's review actions (memo dev/41); omitted → its cards render inert. */
  onApplyProposal?: (proposalId: string) => Promise<unknown>;
  onDismissProposal?: (proposalId: string) => Promise<void>;
  /** Undo a change this agent made; omitted → its change cards offer none. */
  onUndoChange?: (changeId: string) => Promise<unknown>;
  /** dev/71: per-row Solve/Run on a landed plan's card; each tells the row's
   *  `onLine` how far a download on first use of what the node reads has come. */
  onSolvePlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  onRunPlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  /** dev/67-9: Build & validate over the landed plan + its narration. */
  onSimulate?: (mode: "step" | "auto") => Promise<unknown>;
  onCancelSimulate?: () => Promise<void>;
  simulationActivity?: string;
  /** dev/52 Solve (an agent that declares dataflow.orchestrate); omitted → no plan line. */
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
  /** dev/72: opens ANOTHER attachment's chat: the rail's entries, and the
   * delegation entries' and plan-row chips' icon-links route through this.
   * Omitted → entries inert, and no rail. */
  onOpenAgentChat?: (attachmentId: string) => void;
  /** dev/126: record the confirmed dataset selection for this attachment's
   * node (an agent that declares dataset.select, on a node only). */
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
  /** The name of the agent another attachment of this dataflow binds, from
   * the live list: the labels that open its chat name it. Null when the list
   * no longer holds it; omitted, those labels say what they open instead. */
  agentNameOf?: (attachmentId: string) => string | null;
  onSaveIntent?: (intent: string | null) => Promise<void>;
  /** Persist a manual conversation title (memo dev/25). Omitted → the header
   * title is a plain, non-editable label. */
  onSaveTitle?: (title: string) => Promise<void>;
  /** The dataflow's goal (the spec's `task`), on the line under the header. */
  goal?: string;
  /** Keep an edited goal: the dataflow's, so every agent's chat shows it.
   * Omitted → no Goal line. */
  onSaveGoal?: (goal: string) => void;
  onClearConversation?: () => Promise<void>;
  /** The skills this chat's next run lists, which `/` in the composer offers;
   * read each time that list opens. Omitted → `/` is a plain character. */
  loadSkills?: () => Promise<RunSkill[]>;
}> = ({
  attachment,
  turns,
  viewerAccount = null,
  installsWaitForOwner = false,
  targetName = null,
  attachments,
  targetNameOf,
  workingOf,
  presented = true,
  onExitComplete,
  loadingHistory = false,
  historyError = null,
  onRetryHistory,
  onSend,
  onClose,
  toolActivity = [],
  runStatus,
  waitingAsks = [],
  onStopTurn,
  onWithdrawAsk,
  onApplyProposal,
  onDismissProposal,
  onUndoChange,
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
  agentNameOf,
  onSaveIntent,
  onSaveTitle,
  goal,
  onSaveGoal,
  onClearConversation,
  loadSkills,
}) => {
  // A link the agent writes to another Curio page leaves this dataflow, so it
  // asks first when there is unsaved work, like every other way out of it.
  const navigate = useNavigate();
  const { projectDirty, whenChangesKept } = useFlowContext();
  // Its question is asked over the panel: ModalShell's default layer is under it.
  const { leave, dialog: leaveDialog } = useLeaveGuard(Boolean(projectDirty), LEAVE_DATAFLOW, {
    settle: whenChangesKept,
    layer: "overlay",
  });
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  // The app's own dialog, not the browser's (#197).
  const [confirmingClear, setConfirmingClear] = useState(false);
  // Inline click-to-edit conversation title (memo dev/25).
  const title = useConversationTitle(attachment, onSaveTitle);
  // The dataflow's goal, edited on its line under the header.
  const goalLine = useGoalLine(goal, onSaveGoal);
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
  // attachment's install mirror: it self-clears on apply/dismiss: and
  // marks only the NEWEST reply. A review of a change saved before agents
  // changed the dataflow directly awaits nothing: it can only be dismissed.
  const pendingReview =
    attachment.activeProposal?.status === "pending" && !landsAsAChange(attachment.activeProposal.tool);
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
  // The conversation's tokens, More's Tokens used: persisted Actuals plus the
  // in-flight run's interim sums (dev/37: provider-reported only, never an
  // estimate), and how many replies reported theirs. None while history
  // hydrates or while nothing was ever reported.
  const chatTokens = useMemo(() => {
    const live = runInFlight ? runStatus?.liveUsage : null;
    const totals = sessionTokenTotals(turns, live);
    if (!totals || loadingHistory) return null;
    const input = totals.inputTokens ?? 0;
    const output = totals.outputTokens ?? 0;
    if (input + output <= 0) return null;
    const replies = turns.filter((t) => t.execution?.usage).length + (live ? 1 : 0);
    return { input, output, replies };
  }, [turns, runInFlight, runStatus?.liveUsage, loadingHistory]);
  // A running turn never holds the composer back: a message sent meanwhile is
  // asked at once and waits its turn on the server. When the provider wires a
  // status (null = wired, idle) it follows each attachment's asks, so the
  // panel-local `sending` flag never leaks into another chat as agents are
  // cycled. Unwired (tests, previews): the local flag governs.
  const sendBusy = runStatus === undefined ? sending : false;
  // Stop asked for the running turn: it stops at its next step.
  const [stopping, setStopping] = useState(false);
  useEffect(() => {
    if (!runInFlight) setStopping(false);
  }, [runInFlight]);
  const stop = () => {
    if (!onStopTurn || stopping) return;
    setStopping(true);
    onStopTurn().catch(() => setStopping(false));
  };

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
  // while renaming or editing the goal, Escape cancels that edit instead
  // (handled on its input).
  useEffect(() => {
    // A no-op while the panel is sliding out (#295): it is still mounted, so
    // the listener is still attached, and closing something already closing
    // would restart the fallback timer against a panel nobody can see.
    if (!presented) return;
    const onKey = (e: KeyboardEvent) => {
      // A layer over the chat answered this Escape as it closed: a menu of
      // the chat's own, or a dialog. In a browser its close is committed
      // before this listener runs, so the stack below no longer counts it.
      if (escapeAnswered(e)) return;
      // An open modal owns Escape. API Settings and agent import are raised
      // over this panel, and this listener is on window in the bubble phase,
      // so the modal cannot stop it firing. It has to stand down itself, or
      // dismissing the dialog closed the chat behind it as well.
      if (modalStackDepth() > 0) return;
      if (e.key === "Escape" && !title.editing && !goalLine.editing) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, title.editing, goalLine.editing, presented]);

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
  // What the agent is attached to: the header's words, Clear's question.
  const target = targetPhraseFor(attachment, targetName);
  const orchestrates = declaresCapability(attachment, ORCHESTRATE_CAPABILITY);
  const turnActions = {
    onComposePrompt: composePrompt,
    onInternalLink: (to: string) => leave(() => navigate(to)),
    onOpenAgentChat,
    delegateExists,
    agentNameOf,
    onRecordDatasetSelection,
    onImportDataset,
    onApplyProposal,
    beginPackageReview: packageReview.beginReview,
    onDismissProposal,
    onUndoChange,
    onSolvePlanNode,
    onRunPlanNode,
    installsWaitForOwner,
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
      {attachments && onOpenAgentChat ? (
        <AgentRail
          attachments={attachments}
          selectedId={attachment.attachmentId}
          onOpen={onOpenAgentChat}
          targetNameOf={
            targetNameOf ?? ((a) => (a.attachmentId === attachment.attachmentId ? targetName : null))
          }
          workingOf={workingOf ?? ((a) => workingText(a))}
        />
      ) : null}
      <div className={styles.column}>
        <ChatHeader
          category={attachment.category}
          title={
            <ConversationTitle agentName={attachment.name} displayName={displayName} editable={Boolean(onSaveTitle)} title={title} />
          }
          targetLabel={target.header}
          targetTooltip={targetTooltipFor(attachment)}
          titleError={title.error}
          onRename={onSaveTitle ? title.start : undefined}
          onClear={onClearConversation ? () => setConfirmingClear(true) : undefined}
          tokens={chatTokens}
          onClose={onClose}
        />
        {onSaveGoal ? <GoalLine goal={goal ?? ""} state={goalLine} /> : null}

        {/* Solve this node, in a node agent's chat; the dev/52 plan line, in
            the chat of an agent that declares dataflow.orchestrate, one that
            plans a dataflow and solves it. */}
        {onSolveNode && attachment.target.kind === "node" ? (
          <NodeSolveRow
            onSolveNode={onSolveNode}
            onOpenChat={onOpenAgentChat}
            agentNameOf={agentNameOf}
            activity={solveNodeActivity}
            live={attachment.liveJob?.status === "running" && attachment.liveJob.kind === "solve-node"}
          />
        ) : null}
        {orchestrates && onSolve ? (
          <AgentBuilderStrip
            attachment={attachment}
            onSolve={onSolve}
            solveProgress={solveProgress}
            solveErrors={solveErrors}
            solveRemedies={solveRemedies}
            onOpenChat={onOpenAgentChat}
            agentNameOf={agentNameOf}
            solveWaiting={solveWaiting}
            solveEndedBy={solveEndedBy}
            solvePass={solvePass}
            onSolveNode={onSolveOneNode}
            solveWave={solveWave}
            solveNotices={solveNotices}
            onCancelSolve={onCancelSolve}
            onApplyProposal={onApplyProposal}
            onDismissProposal={onDismissProposal}
            onSimulate={onSimulate}
            onCancelSimulate={onCancelSimulate}
            simulationActivity={simulationActivity}
          />
        ) : null}

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
            orchestrates && onSolve ? (
              // The planning templates, while the conversation is empty.
              <div className={styles.emptyChat}>
                <p className={styles.emptyChatText}>
                  Ask for a dataflow, or start from one of these:
                  <span className={styles.emptyChatSub}>
                    They fill the message box; nothing is sent until you press Send.
                  </span>
                </p>
                <PlanningTemplates onComposePrompt={composePrompt} />
              </div>
            ) : (
              <div className={styles.systemLine}>Ask this agent something to get started.</div>
            )
          ) : (
            turns.map((t, i) =>
              t.role === "user" ? (
                writtenBySomeoneElse(t.by, viewerAccount) ? (
                  // A message someone else wrote names its writer above it.
                  <div key={i} className={styles.userTurn} data-curio-writer={t.by?.name}>
                    <div className={styles.msgWriter}>{t.by?.name}</div>
                    <div className={styles.msgUser}>{t.text}</div>
                  </div>
                ) : (
                  <div key={i} className={styles.msgUser}>
                    {t.text}
                  </div>
                )
              ) : (
                <AgentTurn
                  key={i}
                  turn={t}
                  attachment={attachment}
                  tint={tint}
                  meta={turnMetaFor(t, i, metaCtx)}
                  actions={turnActions}
                  canvasUnchanged={canvasUnchangedFor(attachment, turns, i)}
                />
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
          {waitingAsks.map((ask) => (
            <WaitingAskRow key={ask.askId} ask={ask} viewerAccount={viewerAccount} onWithdraw={onWithdrawAsk} />
          ))}
        </div>

        {/* Jump to latest, in a row of its own above the composer: it covers
            no message. */}
        {!atBottom ? (
          <div className={styles.jumpRow}>
            <TranscriptJumpButton visible onJump={jumpToLatest} count={unreadCount} focusFallbackRef={messagesRef} />
          </div>
        ) : null}

        {suggested && suggested.alternatives.length > 0 ? (
          <SuggestedPromptsRow alternatives={suggested.alternatives} onPick={setInput} />
        ) : null}

        <Composer
          agentName={attachment.name}
          value={input}
          onChange={setInput}
          onSend={() => void send()}
          busy={sendBusy}
          textareaRef={composerRef}
          loadSkills={loadSkills}
          // While a turn runs, Stop takes Send's place: anyone who works with
          // the dataflow's agents may stop it.
          onStop={runInFlight && onStopTurn ? stop : undefined}
          stopping={stopping}
        />
      </div>
      {/* dev/84: the reviewed package install, over the page through
          ModalShell: the panel's transform would make a fixed box inside it
          as small as the panel. Its Install button fires the proposal's
          apply; Cancel, Escape or the backdrop keep it pending. */}
      {packageReview.candidate ? (
        <InstallPermissionsModal
          layer="overlay"
          pkg={packageReview.candidate.pkg}
          conflicts={packageReview.candidate.conflicts}
          busy={packageReview.busy}
          onCancel={packageReview.cancel}
          onConfirm={() => void packageReview.confirm()}
        />
      ) : null}
      {confirmingClear ? (
        <ClearConversationDialog
          target={target.object}
          onConfirm={() => {
            setConfirmingClear(false);
            void onClearConversation?.();
          }}
          onCancel={() => setConfirmingClear(false)}
        />
      ) : null}
      {leaveDialog}
    </div>
  );
};
