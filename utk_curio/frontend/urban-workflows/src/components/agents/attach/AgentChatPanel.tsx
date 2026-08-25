import React, { useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faArrowUp,
  faChevronLeft,
  faChevronRight,
  faGear,
  faPen,
  faRobot,
  faTrashCan,
  faXmark,
} from "@fortawesome/free-solid-svg-icons";
import type {
  AgentAttachment,
  AgentCardPart,
  AgentDatasetCandidatesPart,
  AgentDelegationPart,
  AgentProposalPart,
  AgentSessionTurn,
  AgentSuggestedPromptsPart,
} from "../../../api/agentsApi";
import { agentCategoryKey } from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import { attachmentDisplayName, TITLE_MAX_CHARS } from "./attachmentDisplayName";
import { AgentBuilderStrip } from "./AgentBuilderStrip";
import { AgentChatCard } from "../content/AgentChatCard";
import { AgentDatasetCandidatesCard } from "../content/AgentDatasetCandidatesCard";
import { AgentDelegationEntry } from "../content/AgentDelegationEntry";
import { AgentReviewCard } from "../content/AgentReviewCard";
import { SafeAgentContent } from "../content/SafeAgentContent";
import { TranscriptJumpButton } from "./TranscriptJumpButton";
import { useTranscriptAutoScroll } from "./useTranscriptAutoScroll";
import { useAutoGrowTextarea } from "./useAutoGrowTextarea";
import { usePackageInstallReview } from "./usePackageInstallReview";
// dev/84: genuine cross-feature reuse — agent package proposals apply through
// the SAME install review the Nodes Catalog drawer uses, never a duplicate.
import { InstallPermissionsDialog } from "../../packages/publishing/InstallPermissionsDialog";
import { AgentRunStatusLine } from "./AgentRunStatusLine";
import { AgentSessionTokenCounter } from "./AgentSessionTokenCounter";
import {
  sessionTokenTotals,
  turnStatusDisplay,
  type AgentRunStatus,
  type RunStatusDisplay,
} from "./agentRunStatus";
import styles from "./AgentChatPanel.module.css";

/** Heuristic: prompts longer than this get the clamp + expand toggle. */
const INTENT_CLAMP_CHARS = 280;

/**
 * Chat panel for one attached agent, styled to the approved concept screens
 * (docs/08 anatomy + the docs/03 chat-feedback visual system).
 *
 * Per DEC-042 (dev/21) the opened agent view has ONE dark top header carrying
 * the master agent identity, the ‹ › agent-cycling arrows (walking all
 * attachments in the dataflow), the identification details (attached target +
 * session chip), and Close — no Pin, and no static "Agents Catalog" bar (that
 * chrome is exclusive to the Agents Roster drawer). Below the header: the
 * intent-as-first-message transcript and pill input, unchanged.
 *
 * Presentational: the transcript and intent live in AgentAttachmentsProvider
 * (server-persisted session, memo dev/20), so closing/reopening restores the
 * conversation. Closing never detaches the agent.
 */
export const AgentChatPanel: React.FC<{
  attachment: AgentAttachment;
  turns: AgentSessionTurn[];
  /** 1-based position among all attached agents (for the `idx / total` label). */
  index?: number;
  /** Total attached agents in the dataflow. */
  total?: number;
  /** Cycle to the previous/next attachment; omitted → that arrow is disabled. */
  onPrev?: () => void;
  onNext?: () => void;
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
  onOpenSettings?: () => void;
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
  /** dev/63: cancel the running solve. */
  onCancelSolve?: () => Promise<void>;
  /** dev/72: opens ANOTHER attachment's chat — the delegation entries' and
   * plan-row chips' icon-links route through this. Omitted → entries inert. */
  onOpenAgentChat?: (attachmentId: string) => void;
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
  index = 1,
  total = 1,
  onPrev,
  onNext,
  loadingHistory = false,
  historyError = null,
  onRetryHistory,
  onSend,
  onClose,
  toolActivity = [],
  runStatus,
  onOpenSettings,
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
  solveProgress,
  solveErrors,
  onCancelSolve,
  onOpenAgentChat,
  delegateExists,
  onSaveIntent,
  onSaveTitle,
  onClearConversation,
}) => {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [intentExpanded, setIntentExpanded] = useState(false);
  const [editingIntent, setEditingIntent] = useState(false);
  const [intentDraft, setIntentDraft] = useState("");
  const [savingIntent, setSavingIntent] = useState(false);
  const [intentError, setIntentError] = useState<string | null>(null);
  // Inline click-to-edit conversation title (memo dev/25): only the custom
  // portion after "<name>: " is editable; the template-name prefix is fixed.
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  /** Optimistic value shown between commit and the reloaded attachment. */
  const [pendingTitle, setPendingTitle] = useState<string | null>(null);
  const [titleError, setTitleError] = useState<string | null>(null);
  const titleEditDone = useRef(true);
  const wasEditingTitle = useRef(false);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const titleButtonRef = useRef<HTMLButtonElement | null>(null);
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
  const { textareaRef: composerRef } = useAutoGrowTextarea({
    value: input,
    maxHeightPx: 120,
  });
  // dev/84: package.install proposals apply THROUGH the package install
  // review dialog — beginReview's promise spans the whole dialog round-trip,
  // so the review card's busy/error handling covers it.
  const packageReview = usePackageInstallReview(onApplyProposal);

  // Per-reply execution status (memo dev/80, amended: the status rides each
  // agent message, not a global strip). The review chip derives from the
  // attachment's proposal mirrors — it self-clears on apply/dismiss — and
  // marks only the NEWEST reply.
  const pendingReview =
    attachment.activeProposal?.status === "pending" ||
    attachment.planProposal?.status === "pending";
  const runInFlight = runStatus?.phase === "running";
  const lastAgentIdx = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) if (turns[i].role === "agent") return i;
    return -1;
  }, [turns]);
  /** The meta line under one agent turn: the streaming reply shows the live
   * running indicator; finalized replies show their persisted execution
   * record; the newest reply falls back to the live run record when an old
   * server sent no execution fields — so a final message never renders bare. */
  const turnMeta = (t: AgentSessionTurn, i: number): RunStatusDisplay | null => {
    const isLast = i === turns.length - 1;
    if (runInFlight && isLast && t.role === "agent" && !t.error && runStatus)
      return { kind: "running", startedAt: runStatus.startedAt };
    const derived = turnStatusDisplay(t, {
      pendingReview: i === lastAgentIdx && pendingReview,
    });
    if (derived) {
      // The just-failed reply's elapsed-at-failure lives on the run record
      // (client error turns carry no execution).
      if (
        derived.kind === "error" &&
        derived.durationMs == null &&
        isLast &&
        runStatus?.phase === "error"
      )
        return { ...derived, durationMs: runStatus.durationMs };
      return derived;
    }
    if (isLast && t.role === "agent" && !t.error && runStatus?.phase === "done")
      return {
        kind: "done",
        durationMs: runStatus.durationMs,
        usage: runStatus.usage ?? null,
        pendingReview: i === lastAgentIdx && pendingReview,
      };
    return null;
  };
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

  // SUGGESTED PROMPTS (memo dev/39, docs/08): only the newest turn's part
  // counts — once the user replies, earlier follow-ups are stale noise.
  const suggested = useMemo<AgentSuggestedPromptsPart | null>(() => {
    const last = turns[turns.length - 1];
    if (!last || last.role !== "agent" || last.error) return null;
    const part = (last.content ?? []).find((p) => p.type === "suggestedPrompts");
    return (part as AgentSuggestedPromptsPart | undefined) ?? null;
  }, [turns]);

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

  const tint =
    styles[`tint_${agentCategoryKey(attachment.category)}` as keyof typeof styles] ??
    styles.tint_default;

  const targetLabel =
    attachment.target.kind === "canvas"
      ? "canvas"
      : `${attachment.target.kind} ${attachment.target.targetId ?? ""}`.trim();

  // Escape dismisses the chat (close only — the attachment is untouched);
  // while renaming, Escape cancels the edit instead (handled on the input).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !editingTitle) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, editingTitle]);

  // Cycling to another agent discards any in-progress rename state.
  useEffect(() => {
    titleEditDone.current = true;
    setEditingTitle(false);
    setPendingTitle(null);
    setTitleError(null);
  }, [attachment.attachmentId]);

  // The reloaded attachment is authoritative: once its title changes (the
  // save round-tripped), it supersedes the optimistic value.
  useEffect(() => {
    setPendingTitle(null);
  }, [attachment.title]);

  // Entering edit mode focuses the input with the current value selected;
  // leaving it hands focus back to the title control.
  useEffect(() => {
    if (editingTitle) {
      titleInputRef.current?.focus();
      titleInputRef.current?.select();
    } else if (wasEditingTitle.current) {
      titleButtonRef.current?.focus();
    }
    wasEditingTitle.current = editingTitle;
  }, [editingTitle]);

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

  const startIntentEdit = () => {
    setIntentDraft(attachment.intent ?? "");
    setIntentError(null);
    setEditingIntent(true);
  };

  const saveIntent = async () => {
    if (!onSaveIntent || savingIntent) return;
    setSavingIntent(true);
    setIntentError(null);
    try {
      // An emptied draft clears the override → falls back to the prompt source.
      await onSaveIntent(intentDraft.trim() ? intentDraft : null);
      setEditingIntent(false);
    } catch (e) {
      setIntentError(e instanceof Error ? e.message : "Failed to save the intent");
    } finally {
      setSavingIntent(false);
    }
  };

  const clearConversation = async () => {
    if (!onClearConversation) return;
    if (!window.confirm("Clear this conversation? The agent stays attached.")) return;
    await onClearConversation();
  };

  const displayedTitle = pendingTitle ?? attachment.title;

  const startTitleEdit = () => {
    if (!onSaveTitle) return;
    titleEditDone.current = false;
    setTitleDraft(displayedTitle ?? "");
    setTitleError(null);
    setEditingTitle(true);
  };

  // Enter and blur both commit, so a guard keeps the pair to one save; an
  // empty or unchanged draft is a cancel (deleting a title is out of scope).
  const finishTitleEdit = (commit: boolean) => {
    if (titleEditDone.current) return;
    titleEditDone.current = true;
    setEditingTitle(false);
    const next = titleDraft.trim();
    if (!commit || !onSaveTitle || !next || next === (displayedTitle ?? "")) return;
    setPendingTitle(next);
    onSaveTitle(next).catch((e) => {
      setPendingTitle(null);
      setTitleError(e instanceof Error ? e.message : "Failed to rename the conversation");
    });
  };

  const intent = attachment.intent;
  const intentLong = (intent?.length ?? 0) > INTENT_CLAMP_CHARS;

  const displayName = attachmentDisplayName({
    name: attachment.name,
    title: displayedTitle ?? null,
  });

  return (
    <div className={styles.panel} role="dialog" aria-label={`Chat with ${displayName}`}>
      <div className={styles.header}>
        <div className={styles.headerRow}>
          <button
            type="button"
            className={styles.cycleBtn}
            aria-label="Previous agent"
            title="Previous agent"
            disabled={!onPrev}
            onClick={onPrev}
          >
            <FontAwesomeIcon icon={faChevronLeft} />
          </button>
          <span className={`${styles.headerBot} ${tint}`} aria-hidden="true">
            <FontAwesomeIcon icon={faRobot} />
          </span>
          {/* Click-to-rename conversation title (memo dev/25): a single click
              (or Enter/Space when focused) swaps the custom portion for an
              inline input; the "<name>: " prefix stays static. No edit icon —
              the affordance is the title itself. */}
          {editingTitle ? (
            <span className={`${styles.title} ${styles.titleEditing}`}>
              <span className={styles.titlePrefix}>{attachment.name}: </span>
              <input
                ref={titleInputRef}
                className={styles.titleInput}
                aria-label="Conversation title"
                maxLength={TITLE_MAX_CHARS}
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    finishTitleEdit(true);
                  } else if (e.key === "Escape") {
                    e.stopPropagation();
                    finishTitleEdit(false);
                  }
                }}
                onBlur={() => finishTitleEdit(true)}
              />
            </span>
          ) : onSaveTitle ? (
            <button
              type="button"
              ref={titleButtonRef}
              className={`${styles.title} ${styles.titleButton}`}
              aria-label="Rename conversation title"
              title="Click to rename"
              onClick={startTitleEdit}
            >
              {displayName}
            </button>
          ) : (
            <span className={styles.title}>{displayName}</span>
          )}
          <span className={styles.position}>
            {index} / {total}
          </span>
          <button
            type="button"
            className={styles.cycleBtn}
            aria-label="Next agent"
            title="Next agent"
            disabled={!onNext}
            onClick={onNext}
          >
            <FontAwesomeIcon icon={faChevronRight} />
          </button>
          <span className={styles.headerSpacer} />
          {onClearConversation ? (
            <button
              type="button"
              className={styles.headerBtn}
              aria-label="Clear conversation"
              title="Clear conversation"
              onClick={clearConversation}
            >
              <FontAwesomeIcon icon={faTrashCan} />
            </button>
          ) : null}
          <button
            type="button"
            className={styles.headerBtn}
            aria-label="Close chat"
            title="Close chat"
            onClick={onClose}
          >
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </div>
        <div className={styles.headerRow}>
          <span className={styles.subtitle}>Attached to {targetLabel}</span>
          {titleError ? <span className={styles.titleError}>{titleError}</span> : null}
          <span className={styles.headerSpacer} />
          <span className={styles.sessionChip} title={`session ${attachment.sessionId}`}>
            session {attachment.sessionId.slice(0, 8)}
          </span>
        </div>
      </div>

      {/* The dev/52 builder strip: Dataflow Builder attachments only — every
          other agent's chat is pixel-identical. */}
      {onSolve && attachment.coord.startsWith("agent.dataflow-builder@") ? (
        <AgentBuilderStrip
          attachment={attachment}
          onSolve={onSolve}
          solveProgress={solveProgress}
          solveErrors={solveErrors}
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
        {/* ⚙ Attachment settings (docs/08 anatomy, memo dev/42): the labeled
            cog sits at the top of the white content area, beneath the DEC-042
            header — never in it. */}
        {onOpenSettings ? (
          <button
            type="button"
            className={styles.attachmentSettingsBtn}
            aria-haspopup="dialog"
            onClick={onOpenSettings}
          >
            <FontAwesomeIcon icon={faGear} aria-hidden="true" /> Attachment settings
          </button>
        ) : null}
        {/* The initial intent reads as the conversation's first message (a
            plain user bubble), collapsed by default, with show more/less and
            an edit pencil. */}
        {editingIntent ? (
          <div className={styles.intentEditor}>
            <textarea
              className={styles.intentTextarea}
              aria-label="Initial intent"
              value={intentDraft}
              onChange={(e) => setIntentDraft(e.target.value)}
            />
            <div className={styles.intentActions}>
              <button
                type="button"
                className={styles.intentSave}
                disabled={savingIntent}
                onClick={saveIntent}
              >
                {savingIntent ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                className={styles.intentCancel}
                onClick={() => setEditingIntent(false)}
              >
                Cancel
              </button>
              {intentError ? <span className={styles.intentError}>{intentError}</span> : null}
            </div>
          </div>
        ) : (
          <div className={styles.intentMsg}>
            <div
              className={[
                styles.msgUser,
                !intentExpanded && intentLong ? styles.intentClamped : "",
                !intent ? styles.intentPlaceholder : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {intent ?? "No instruction prompt available for this agent."}
            </div>
            <div className={styles.intentControls}>
              {intentLong ? (
                <button
                  type="button"
                  className={styles.intentToggle}
                  onClick={() => setIntentExpanded((v) => !v)}
                >
                  {intentExpanded ? "Show less" : "Show more"}
                </button>
              ) : null}
              {onSaveIntent ? (
                <button
                  type="button"
                  className={styles.intentEdit}
                  aria-label="Edit initial intent"
                  title="Edit initial intent"
                  onClick={startIntentEdit}
                >
                  <FontAwesomeIcon icon={faPen} />
                </button>
              ) : null}
            </div>
          </div>
        )}
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
              <div key={i} className={styles.agentRow}>
                <span className={`${styles.agentRowAvatar} ${tint}`} aria-hidden="true">
                  <FontAwesomeIcon icon={faRobot} />
                </span>
                <div className={styles.agentCol}>
                <div className={`${styles.msgAgent} ${t.error ? styles.msgError : ""}`}>
                  {/* Agent rich content renders ONLY through the safe renderer
                      (REQ-SEC-002); error markers are server-composed plain
                      text. Cards are informational plain data (docs/08);
                      proposals render the review card (dev/41). */}
                  {t.error ? t.text : <SafeAgentContent text={t.text} />}
                  {(t.content ?? [])
                    .filter((p): p is AgentCardPart => p.type === "card")
                    .map((card, j) => (
                      <AgentChatCard key={j} card={card} tintClassName={tint} />
                    ))}
                  {(t.content ?? [])
                    .filter(
                      (p): p is AgentDatasetCandidatesPart =>
                        p.type === "datasetCandidates",
                    )
                    .map((part, j) => (
                      <AgentDatasetCandidatesCard
                        key={`cand-${j}`}
                        part={part}
                        tintClassName={tint}
                        onComposePrompt={composePrompt}
                      />
                    ))}
                  {(t.content ?? [])
                    .filter((p): p is AgentDelegationPart => p.type === "delegation")
                    .map((part, j) => (
                      <AgentDelegationEntry
                        key={`dlg-${j}`}
                        part={part}
                        onOpenChat={onOpenAgentChat}
                        delegateExists={delegateExists}
                      />
                    ))}
                  {(t.content ?? [])
                    .filter((p): p is AgentProposalPart => p.type === "proposal")
                    .map((part, j) => (
                      <AgentReviewCard
                        key={part.proposalId ?? j}
                        part={part}
                        tintClassName={tint}
                        onApply={
                          part.tool === "package.install" && onApplyProposal
                            ? (proposalId) =>
                                packageReview.beginReview(
                                  proposalId,
                                  part.pins?.dirName ?? "",
                                )
                            : onApplyProposal
                        }
                        onDismiss={onDismissProposal}
                        onApplyPlanNode={onApplyPlanNode}
                        onSavePlanGoal={onSavePlanGoal}
                        onApplyPlanEdges={onApplyPlanEdges}
                        onSolvePlanNode={onSolvePlanNode}
                        onRunPlanNode={onRunPlanNode}
                        onOpenAgentChat={onOpenAgentChat}
                        delegateExists={delegateExists}
                        planNodeState={(() => {
                          // dev/67-5/67-9: the mirror's per-node state feeds
                          // the part whose proposal it mirrors — active OR
                          // parked behind a content review.
                          const mirror =
                            attachment.activeProposal?.proposalId === part.proposalId
                              ? attachment.activeProposal
                              : attachment.planProposal?.proposalId === part.proposalId
                                ? attachment.planProposal
                                : null;
                          return mirror
                            ? {
                                appliedRefs: mirror.appliedRefs ?? [],
                                editedGoals: mirror.editedGoals ?? {},
                                edgeStates: mirror.edgeStates ?? {},
                                // dev/71: the lifecycle ledger for readiness.
                                nodeStates: attachment.builderSession?.nodeStates ?? {},
                                // dev/72: where each ref's content review lives.
                                nodeProposals:
                                  attachment.builderSession?.nodeProposals ?? {},
                              }
                            : undefined;
                        })()}
                      />
                    ))}
                </div>
                {/* Per-reply execution status (dev/80 amendment): running
                    while THIS reply streams, then its own duration + tokens. */}
                {(() => {
                  const meta = turnMeta(t, i);
                  return meta ? (
                    <div className={styles.turnMeta}>
                      <AgentRunStatusLine display={meta} tintClassName={tint} />
                    </div>
                  ) : null;
                })()}
                </div>
              </div>
            ),
          )
        )}
        {toolActivity.map((line, i) => (
          <div key={`tool-${i}`} className={styles.systemLine}>
            {line}
          </div>
        ))}
        {/* The reply hasn't streamed its first delta yet (tool rounds, the
            blocking fallback): a standalone pending row keeps the live
            indicator visible at the tail (dev/80 amendment). */}
        {runInFlight && !streamingTurnVisible && runStatus ? (
          <div className={styles.agentRow}>
            <span className={`${styles.agentRowAvatar} ${tint}`} aria-hidden="true">
              <FontAwesomeIcon icon={faRobot} />
            </span>
            <div className={styles.agentCol}>
              <div className={styles.turnMeta}>
                <AgentRunStatusLine
                  display={{ kind: "running", startedAt: runStatus.startedAt }}
                  tintClassName={tint}
                />
              </div>
            </div>
          </div>
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
      </div>

      {suggested && suggested.alternatives.length > 0 ? (
        <div className={styles.suggestedRow} role="group" aria-label="Suggested prompts">
          <span className={styles.suggestedLabel}>Suggested prompts</span>
          {suggested.alternatives.map((alt, i) => (
            <button
              key={i}
              type="button"
              className={styles.suggestedChip}
              title={alt}
              onClick={() => setInput(alt)}
            >
              {alt}
            </button>
          ))}
        </div>
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

      <div className={styles.footer}>
        {/* Enter sends; Shift+Enter falls through to the textarea's native
            newline. An in-flight IME composition's commit-Enter never sends. */}
        <textarea
          ref={composerRef}
          className={styles.input}
          value={input}
          rows={1}
          aria-label="Message this agent"
          placeholder="Message this agent…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button
          type="button"
          className={styles.send}
          aria-label="Send"
          title="Send"
          disabled={sendBusy || !input.trim()}
          onClick={send}
        >
          {sendBusy ? "…" : <FontAwesomeIcon icon={faArrowUp} />}
        </button>
      </div>
    </div>
  );
};
