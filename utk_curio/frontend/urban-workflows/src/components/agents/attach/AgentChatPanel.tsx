import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useFlowContext } from "../../../providers/FlowProvider";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import {
  attachmentDisplayName,
  CONTENT_GENERATE_CAPABILITY,
  DATASET_SELECT_CAPABILITY,
  declaresCapability,
  ORCHESTRATE_CAPABILITY,
  sessionTokenTotals,
  writtenBySomeoneElse,
  type AgentAttachment,
  type AgentSessionTurn,
  type AgentRunStatus,
  type RunSkill,
} from "../../../services/agents";
import { buildRunningOn, holdsSourceCardFor } from "../../../services/agents/planBuild";
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
import { IntentDialog } from "./chat/IntentDialog";
import { PendingReplyRow } from "./chat/PendingReplyRow";
import { SuggestedPromptsRow, suggestionsOf } from "./chat/SuggestedPromptsRow";
import { useConversationTitle } from "./chat/useConversationTitle";
import { useGoalLine } from "./chat/useGoalLine";
import { useRunDetails } from "./chat/runDetails";
import { WaitingAskRow } from "./chat/WaitingAskRow";
import {
  askedLine,
  canvasUnchangedFor,
  shownInChat,
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
 * conversation, Edit initial intent, Show run details, Clear conversation,
 * Tokens used) and Close; no Pin, and no static "Agent Catalog" bar (that
 * chrome is exclusive to the Agents Roster drawer). Under the header: the
 * dataflow's goal (`GoalLine`), the same in every agent's chat; the plan line
 * of an agent that solves a dataflow, or Solve this node in a node agent's;
 * then the transcript, the newest reply's suggestions behind one button, and
 * the pill composer, empty until the person writes or picks something. A task
 * another agent asked of this one reads as one quiet line, and a turn the
 * runtime keeps for the agents alone is not drawn.
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
  /** Why the server refused the last Undo, Apply or Dismiss of a card of this
   * chat, by the card's change or proposal id: the card says it until the
   * user acts on it again, though a read of the chat draws it anew. */
  refusals?: Record<string, string>;
  /** dev/71: per-row Solve/Run on a landed plan's card; each tells the row's
   *  `onLine` how far a download on first use of what the node reads has come. */
  onSolvePlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  onRunPlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  /** dev/67-9: Build & validate over the landed plan + its narration. */
  onSimulate?: (mode: "step" | "auto") => Promise<unknown>;
  onCancelSimulate?: () => Promise<void>;
  simulationActivity?: string;
  /** The build the chat runs for this agent, step or auto: the plan line
   *  shows it and its Stop, however often it is drawn again. */
  simulating?: "step" | "auto" | null;
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
  /** dev/118: the live batch's current topological wave. */
  solveWave?: import("../../../services/agents").AgentSolveWave;
  /** dev/118: per-node notices that are not errors (pending/skipped reasons, written-not-executed). */
  solveNotices?: Record<string, string>;
  /** dev/63: cancel the running solve. */
  onCancelSolve?: () => Promise<void>;
  /** dev/115 (Amendment A2): the per-node Solve: offered when this agent is
   * attached to a node and solves nodes (`solvesNodes`, the server's own
   * answer); runs the node's current code in the sandbox, fixes errors,
   * re-runs, and lands an executed review. Omitted → no row. */
  onSolveNode?: () => Promise<unknown>;
  /** Why the per-node Solve may not start now: a build runs on the node's
   * plan, or its plan's row Solves it. */
  solveNodeBlocker?: string | null;
  /** dev/115: the running per-node Solve's narration. */
  solveNodeActivity?: string | null;
  /** dev/72: opens ANOTHER attachment's chat: the rail's entries, and the
   * delegation entries' and plan-row chips' icon-links route through this.
   * Omitted → entries inert, and no rail. */
  onOpenAgentChat?: (attachmentId: string) => void;
  /** dev/126: record the confirmed dataset selection for this attachment's
   * node (an agent that declares dataset.select, on a node only), naming the
   * card it was made on (*discoveryId*) when the card has an id. */
  onRecordDatasetSelection?: (
    picks: import("../../../services/agents").AgentDatasetPick[],
    discoveryId?: string,
  ) => Promise<import("../../../services/agents").AgentDatasetSelection>;
  /** Record a pick on a node's candidates card in this chat, which asked for
   * them: on the route of the node's Dataset Finder, naming the card. */
  onRecordSourcePick?: (
    finderAttachmentId: string,
    picks: import("../../../services/agents").AgentDatasetPick[],
    discoveryId?: string,
  ) => Promise<import("../../../services/agents").AgentDatasetSelection>;
  /** Whether a node is on the canvas: a candidates card whose Finder is gone
   * says whether its node went too. Omitted, every node is taken as there. */
  nodeOnCanvas?: (nodeId: string) => boolean;
  /** The name a node's header shows, null when it is not on the canvas: a
   * change card's title names its node by it. */
  nodeNameOf?: (nodeId: string) => string | null;
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
  refusals,
  onSolvePlanNode,
  onRunPlanNode,
  onSimulate,
  onCancelSimulate,
  simulationActivity,
  simulating = null,
  onSolve,
  onSolveNode,
  solveNodeBlocker = null,
  solveNodeActivity = null,
  solveProgress,
  solveErrors,
  solveRemedies,
  solveWaiting,
  solveEndedBy,
  solvePass,
  solveWave,
  solveNotices,
  onCancelSolve,
  onOpenAgentChat,
  onRecordDatasetSelection,
  onRecordSourcePick,
  nodeOnCanvas,
  nodeNameOf,
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
  // More's Edit initial intent, in a dialog over the panel.
  const [editingIntent, setEditingIntent] = useState(false);
  // The viewer's own Show run details, the same in every chat.
  const [runDetails, setRunDetails] = useRunDetails();
  // The turns the chat draws: a turn the runtime keeps for the agents alone
  // is read by them and never drawn. What a chat counts, follows and suggests
  // is read from these; the cards it holds, from every turn.
  const shownTurns = useMemo(() => turns.filter(shownInChat), [turns]);
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
    content: shownTurns,
    resetKey: attachment.attachmentId,
    ready: !loadingHistory,
    // Turn count, not content: the pill's unread badge (dev/83) counts whole
    // landed messages — streamed chunk growth never increments it.
    itemCount: shownTurns.length,
  });
  /** The last value a template or a candidates card put in the box, so the
   * next may replace it, but never a draft the user actually typed (memo
   * dev/39). */
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
  // agent message, not a global strip).
  const runInFlight = runStatus?.phase === "running";
  const metaCtx = { turns: shownTurns, runStatus, runInFlight };
  // The reply being generated appears in `turns` only from its first delta;
  // until then (tool rounds, the blocking fallback) a standalone pending row
  // at the transcript tail carries the live indicator.
  const streamingTurnVisible = runInFlight && shownTurns[shownTurns.length - 1]?.role === "agent";
  // The conversation's tokens, More's Tokens used: persisted Actuals plus the
  // in-flight run's interim sums (dev/37: provider-reported only, never an
  // estimate), and how many replies reported theirs. None while history
  // hydrates or while nothing was ever reported. While a reply runs, the count
  // can still grow, and pulses as the counter by the composer did.
  const chatTokens = useMemo(() => {
    const live = runInFlight ? runStatus?.liveUsage : null;
    const totals = sessionTokenTotals(turns, live);
    if (!totals || loadingHistory) return null;
    const input = totals.inputTokens ?? 0;
    const output = totals.outputTokens ?? 0;
    if (input + output <= 0) return null;
    const replies = turns.filter((t) => t.execution?.usage).length + (live ? 1 : 0);
    return { input, output, replies, live: runInFlight };
  }, [turns, runInFlight, runStatus?.liveUsage, loadingHistory]);
  // A running turn never holds the composer back: a message sent meanwhile is
  // asked at once and waits its turn on the server. When the provider wires a
  // status (null = wired, idle) it follows each attachment's asks, so the
  // panel-local `sending` flag never leaks into another chat as agents are
  // cycled. Unwired (tests, previews): the local flag governs.
  const sendBusy = runStatus === undefined ? sending : false;
  // Stop asked for the running turn: it stops at its next step. Kept for that
  // turn alone, by its chat and its start: the rail's next chat in this panel
  // never shows it, and back on this chat while the turn runs, it still does.
  const runKey = runInFlight && runStatus ? `${attachment.attachmentId}@${runStatus.startedAt}` : null;
  const [stopAskedFor, setStopAskedFor] = useState<string | null>(null);
  const stopping = runKey !== null && stopAskedFor === runKey;
  const stop = () => {
    if (!onStopTurn || !runKey || stopping) return;
    setStopAskedFor(runKey);
    onStopTurn().catch(() => setStopAskedFor((asked) => (asked === runKey ? null : asked)));
  };

  // The newest reply's suggestions, behind one button: the message box stays
  // empty for the person's own words until they pick one.
  const suggestions = useMemo(() => suggestionsOf(suggestedPromptsOf(shownTurns)), [shownTurns]);
  const pickSuggestion = (prompt: string) => {
    setInput(prompt);
    lastPrefill.current = prompt;
    composerRef.current?.focus();
  };

  // A planning template, and the selection of a candidates card with no pick
  // of its own (dev/50), put their message in the box through the same rule:
  // one replaces what the last of them put there, never a draft the user
  // actually typed.
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
  // The candidates cards this chat holds, by the node they are for and by
  // the id of the search that minted them.
  const sourceCardsOf = (nodeId: string) =>
    Array.from(messagesRef.current?.querySelectorAll<HTMLElement>("[data-curio-source-pick]") ?? []).filter(
      (card) => card.getAttribute("data-curio-source-pick") === nodeId,
    );
  // Brings the card *discoveryId* into view when this chat holds it, else
  // opens the chat of its node's Finder (*finderAttachmentId*), which does.
  const showCardOf = (discoveryId: string | null, finderAttachmentId: string | null) => {
    const card = discoveryId
      ? Array.from(messagesRef.current?.querySelectorAll<HTMLElement>("[data-curio-discovery]") ?? []).find(
          (el) => el.getAttribute("data-curio-discovery") === discoveryId,
        )
      : undefined;
    if (card) card.scrollIntoView({ block: "nearest" });
    else if (finderAttachmentId && finderAttachmentId !== attachment.attachmentId) onOpenAgentChat?.(finderAttachmentId);
  };
  const turnActions = {
    onComposePrompt: composePrompt,
    onInternalLink: (to: string) => leave(() => navigate(to)),
    onOpenAgentChat,
    delegateExists,
    agentNameOf,
    onRecordDatasetSelection,
    onRecordSourcePick,
    // A node's candidates card in this chat reads the node's Finder's record
    // from the live list: null once the list no longer holds the Finder, and
    // undefined when this chat has no list to read.
    attachmentOf: (attachmentId: string) =>
      attachments ? attachments.find((a) => a.attachmentId === attachmentId) ?? null : undefined,
    nodeOnCanvas,
    nodeNameOf,
    showCardOf,
    targetName,
    // No plan row's Solve starts while a build runs on this agent's plan.
    buildRunning: buildRunningOn(attachment, simulating) !== null,
    // What runs on the plan now: each row of its card says its node's.
    planLive: { solveProgress, solveErrors, solveNotices, solveWaiting, simulationActivity },
    // A plan row's name opens its node's own agent, the one that writes its
    // code, from the live list.
    nodeChatOf: (nodeId: string) => {
      const own = attachments?.find(
        (a) => a.target.kind === "node" && a.target.targetId === nodeId && declaresCapability(a, CONTENT_GENERATE_CAPABILITY),
      );
      return own ? { attachmentId: own.attachmentId, name: agentNameOf?.(own.attachmentId) ?? own.name } : null;
    },
    onImportDataset,
    onApplyProposal,
    beginPackageReview: packageReview.beginReview,
    onDismissProposal,
    onUndoChange,
    refusalOf: (cardId: string) => refusals?.[cardId] ?? null,
    onSolvePlanNode,
    onRunPlanNode,
    installsWaitForOwner,
  };
  // The node this agent is on, and whether this chat holds the card of its
  // candidates, which its Solve asked for: Show its sources brings the card
  // its Finder's record offers now into view, else the newest for the node.
  const ownNode = attachment.target.kind === "node" ? attachment.target.targetId ?? null : null;
  const ownFinderRecord = ownNode
    ? attachments?.find(
        (a) =>
          a.target.kind === "node" &&
          a.target.targetId === ownNode &&
          declaresCapability(a, DATASET_SELECT_CAPABILITY),
      )?.sourceRecord ?? null
    : null;
  const showSourceCard =
    ownNode && holdsSourceCardFor(turns, ownNode)
      ? () => {
          const cards = sourceCardsOf(ownNode);
          const offered = ownFinderRecord?.discoveryId
            ? cards.find((card) => card.getAttribute("data-curio-discovery") === ownFinderRecord.discoveryId)
            : undefined;
          (offered ?? cards[cards.length - 1])?.scrollIntoView({ block: "nearest" });
        }
      : null;
  // The plan line's Show its sources: the card of the node's candidates this
  // chat holds, the one its Finder's record offers now, else the newest; with
  // none here, the chat of the node's Finder, which holds its own.
  const showSourcesOf = (nodeId: string) => {
    const finder = attachments?.find(
      (a) =>
        a.target.kind === "node" && a.target.targetId === nodeId && declaresCapability(a, DATASET_SELECT_CAPABILITY),
    );
    const cards = sourceCardsOf(nodeId);
    const offered = finder?.sourceRecord?.discoveryId
      ? cards.find((card) => card.getAttribute("data-curio-discovery") === finder.sourceRecord?.discoveryId)
      : undefined;
    const card = offered ?? cards[cards.length - 1];
    if (card) card.scrollIntoView({ block: "nearest" });
    else if (finder) onOpenAgentChat?.(finder.attachmentId);
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
          onEditIntent={onSaveIntent ? () => setEditingIntent(true) : undefined}
          runDetails={{ shown: runDetails, onToggle: () => setRunDetails(!runDetails) }}
          onClear={onClearConversation ? () => setConfirmingClear(true) : undefined}
          tokens={chatTokens}
          onClose={onClose}
        />
        {onSaveGoal ? <GoalLine goal={goal ?? ""} state={goalLine} /> : null}

        {/* Solve this node, in the chat of a node agent the server lets
            Solve its node (`solvesNodes`); the dev/52 plan line, in the chat
            of an agent that declares dataflow.orchestrate, one that plans a
            dataflow and solves it. */}
        {/* Each keyed to its chat: the rail swaps the agent in this one
            panel, and what one chat's Solve or build started is not the
            next chat's. */}
        {onSolveNode && attachment.target.kind === "node" && attachment.solvesNodes === true ? (
          <NodeSolveRow
            key={attachment.attachmentId}
            onSolveNode={onSolveNode}
            onOpenChat={onOpenAgentChat}
            agentNameOf={agentNameOf}
            activity={solveNodeActivity}
            live={attachment.liveJob?.status === "running" && attachment.liveJob.kind === "solve-node"}
            blocker={solveNodeBlocker}
            onShowCard={showSourceCard}
          />
        ) : null}
        {orchestrates && onSolve ? (
          <AgentBuilderStrip
            key={attachment.attachmentId}
            attachment={attachment}
            onSolve={onSolve}
            solveProgress={solveProgress}
            solveErrors={solveErrors}
            solveRemedies={solveRemedies}
            solveWaiting={solveWaiting}
            solveEndedBy={solveEndedBy}
            solvePass={solvePass}
            solveWave={solveWave}
            onCancelSolve={onCancelSolve}
            onShowSources={showSourcesOf}
            runDetails={runDetails}
            onApplyProposal={onApplyProposal}
            onDismissProposal={onDismissProposal}
            onSimulate={onSimulate}
            onCancelSimulate={onCancelSimulate}
            simulationActivity={simulationActivity}
            simulating={simulating}
          />
        ) : null}

        <div className={styles.messages} ref={messagesRef} tabIndex={-1}>
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
          ) : shownTurns.length === 0 && !historyError ? (
            orchestrates && onSolve && (attachment.builderSession?.phase ?? "idle") === "idle" ? (
              // The planning templates, while the conversation is empty and no
              // plan landed: Clear conversation leaves a landed plan, and its
              // line, in place. What a template does is its tooltip.
              <div className={styles.emptyChat}>
                <p className={styles.emptyChatText}>Ask for a dataflow, or start from one of these:</p>
                <PlanningTemplates onComposePrompt={composePrompt} />
              </div>
            ) : (
              <div className={styles.systemLine}>Ask this agent something to get started.</div>
            )
          ) : (
            shownTurns.map((t, i) =>
              t.role === "user" ? (
                askedLine(t) ? (
                  // A task another agent asked of this one: one quiet line,
                  // never a message of the person's.
                  <div key={i} className={styles.askedLine} data-curio-asked="">
                    {askedLine(t)}
                  </div>
                ) : writtenBySomeoneElse(t.by, viewerAccount) ? (
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
                  canvasUnchanged={canvasUnchangedFor(attachment, shownTurns, i)}
                  runDetails={runDetails}
                />
              ),
            )
          )}
          {/* What the running turn does now: its newest step alone. */}
          {toolActivity.length > 0 ? (
            <div className={styles.systemLine}>{toolActivity[toolActivity.length - 1]}</div>
          ) : null}
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

        <SuggestedPromptsRow suggestions={suggestions} onPick={pickSuggestion} />

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
      {editingIntent && onSaveIntent ? (
        <IntentDialog intent={attachment.intent} onSave={onSaveIntent} onClose={() => setEditingIntent(false)} />
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
