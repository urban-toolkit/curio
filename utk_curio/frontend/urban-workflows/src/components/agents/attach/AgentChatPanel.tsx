import React, { useEffect, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faArrowUp, faPen, faRobot, faTrashCan, faXmark } from "@fortawesome/free-solid-svg-icons";
import type { AgentAttachment, AgentSessionTurn } from "../../../api/agentsApi";
import { agentCategoryKey } from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import styles from "./AgentChatPanel.module.css";

/** Heuristic: prompts longer than this get the clamp + expand toggle. */
const INTENT_CLAMP_CHARS = 280;

/**
 * Chat panel for one attached agent, styled to the approved concept screens
 * (docs/08 anatomy + the docs/03 chat-feedback visual system): tinted-avatar
 * header with a clear close control, the pinned editable INITIAL INTENT block
 * (served from the actual prompt source), dark user bubbles / avatar-prefixed
 * agent rows, and a pill input with a circular ↑ send.
 *
 * Presentational: the transcript and intent live in AgentAttachmentsProvider
 * (server-persisted session, memo dev/20), so closing/reopening restores the
 * conversation. Closing never detaches the agent.
 */
export const AgentChatPanel: React.FC<{
  attachment: AgentAttachment;
  turns: AgentSessionTurn[];
  /** True while the session history is loading from the server. */
  loadingHistory?: boolean;
  /** History-load failure message; `onRetryHistory` retries the fetch. */
  historyError?: string | null;
  onRetryHistory?: () => void;
  onSend: (message: string) => Promise<void>;
  onClose: () => void;
  onSaveIntent?: (intent: string | null) => Promise<void>;
  onClearConversation?: () => Promise<void>;
}> = ({
  attachment,
  turns,
  loadingHistory = false,
  historyError = null,
  onRetryHistory,
  onSend,
  onClose,
  onSaveIntent,
  onClearConversation,
}) => {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [intentExpanded, setIntentExpanded] = useState(false);
  const [editingIntent, setEditingIntent] = useState(false);
  const [intentDraft, setIntentDraft] = useState("");
  const [savingIntent, setSavingIntent] = useState(false);
  const [intentError, setIntentError] = useState<string | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);

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

  // Escape dismisses the chat (close only — the attachment is untouched).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

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

  const intent = attachment.intent;
  const intentLong = (intent?.length ?? 0) > INTENT_CLAMP_CHARS;

  return (
    <div className={styles.panel} role="dialog" aria-label={`Chat with ${attachment.name}`}>
      <div className={styles.header}>
        <span className={`${styles.avatar} ${tint}`} aria-hidden="true">
          <FontAwesomeIcon icon={faRobot} />
        </span>
        <div className={styles.headerText}>
          <span className={styles.title}>{attachment.name}</span>
          <span className={styles.subtitle}>Attached to {targetLabel}</span>
        </div>
        <span className={styles.sessionChip} title={`session ${attachment.sessionId}`}>
          session {attachment.sessionId.slice(0, 8)}
        </span>
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

      <div className={styles.intent}>
        <div className={styles.intentHead}>
          <span className={styles.intentLabel} id={`intent-label-${attachment.attachmentId}`}>
            Initial intent
          </span>
          {attachment.intentEdited ? (
            <span className={styles.intentEditedChip}>edited</span>
          ) : null}
          {onSaveIntent && !editingIntent ? (
            <button
              type="button"
              className={styles.headerBtn}
              aria-label="Edit initial intent"
              title="Edit initial intent"
              onClick={startIntentEdit}
            >
              <FontAwesomeIcon icon={faPen} />
            </button>
          ) : null}
        </div>
        {editingIntent ? (
          <>
            <textarea
              className={styles.intentTextarea}
              aria-labelledby={`intent-label-${attachment.attachmentId}`}
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
          </>
        ) : (
          <>
            <div
              className={[
                styles.intentText,
                !intentExpanded && intentLong ? styles.intentClamped : "",
                !intent ? styles.intentPlaceholder : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {intent ?? "No instruction prompt available for this agent."}
            </div>
            {intentLong ? (
              <button
                type="button"
                className={styles.intentToggle}
                onClick={() => setIntentExpanded((v) => !v)}
              >
                {intentExpanded ? "Show less" : "Show more"}
              </button>
            ) : null}
          </>
        )}
      </div>

      <div className={styles.messages} ref={messagesRef}>
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
                  {t.text}
                </div>
              </div>
            ),
          )
        )}
      </div>

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
