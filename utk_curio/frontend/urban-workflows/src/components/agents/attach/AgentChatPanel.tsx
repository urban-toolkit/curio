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
  AgentProposalPart,
  AgentSessionTurn,
  AgentSuggestedPromptsPart,
} from "../../../api/agentsApi";
import { agentCategoryKey } from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import { attachmentDisplayName, TITLE_MAX_CHARS } from "./attachmentDisplayName";
import { AgentChatCard } from "../content/AgentChatCard";
import { AgentReviewCard } from "../content/AgentReviewCard";
import { SafeAgentContent } from "../content/SafeAgentContent";
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
  /** Opens the shared settings modal at the Attached-instance scope (memo
   * dev/42) — the labeled cog beneath the header (the docs/08 anatomy slot;
   * never in the DEC-042 header itself). Omitted → no cog. */
  onOpenSettings?: () => void;
  /** Review-before-apply actions (memo dev/41); omitted → cards render inert. */
  onApplyProposal?: (proposalId: string) => Promise<void>;
  onDismissProposal?: (proposalId: string) => Promise<void>;
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
  onOpenSettings,
  onApplyProposal,
  onDismissProposal,
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
  const messagesRef = useRef<HTMLDivElement | null>(null);
  /** The last value this panel prefilled — so a prefill may replace a prior
   * prefill, but never a draft the user actually typed (memo dev/39). */
  const lastPrefill = useRef("");

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

  const tint =
    styles[`tint_${agentCategoryKey(attachment.category)}` as keyof typeof styles] ??
    styles.tint_default;

  const targetLabel =
    attachment.target.kind === "canvas"
      ? "canvas"
      : `${attachment.target.kind} ${attachment.target.targetId ?? ""}`.trim();

  // Keep the transcript pinned to the newest turn (also after history hydrates).
  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, loadingHistory]);

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
    if (!message || sending) return;
    setInput("");
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

      <div className={styles.messages} ref={messagesRef}>
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
                    .filter((p): p is AgentProposalPart => p.type === "proposal")
                    .map((part, j) => (
                      <AgentReviewCard
                        key={part.proposalId ?? j}
                        part={part}
                        tintClassName={tint}
                        onApply={onApplyProposal}
                        onDismiss={onDismissProposal}
                      />
                    ))}
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

      <div className={styles.footer}>
        <input
          className={styles.input}
          value={input}
          placeholder="Message this agent…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
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
          disabled={sending || !input.trim()}
          onClick={send}
        >
          {sending ? "…" : <FontAwesomeIcon icon={faArrowUp} />}
        </button>
      </div>
    </div>
  );
};
