import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPen } from "@fortawesome/free-solid-svg-icons";

import styles from "../AgentChatPanel.module.css";
import { INTENT_CLAMP_CHARS } from "./chatPanelDerived";

/**
 * The initial intent reads as the conversation's first message (a plain user
 * bubble), collapsed by default, with show more/less and an edit pencil that
 * swaps it for the inline editor (split out of `AgentChatPanel.tsx` by memo
 * dev/142, F4). An emptied draft clears the override → the prompt source.
 */
export const IntentMessage: React.FC<{
  intent: string | null | undefined;
  onSaveIntent?: (intent: string | null) => Promise<void>;
}> = ({ intent, onSaveIntent }) => {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intentLong = (intent?.length ?? 0) > INTENT_CLAMP_CHARS;

  const startEdit = () => {
    setDraft(intent ?? "");
    setError(null);
    setEditing(true);
  };

  const save = async () => {
    if (!onSaveIntent || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSaveIntent(draft.trim() ? draft : null);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save the intent");
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <div className={styles.intentEditor}>
        <textarea
          className={styles.intentTextarea}
          aria-label="Initial intent"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className={styles.intentActions}>
          <button type="button" className={styles.intentSave} disabled={saving} onClick={save}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button type="button" className={styles.intentCancel} onClick={() => setEditing(false)}>
            Cancel
          </button>
          {error ? <span className={styles.intentError}>{error}</span> : null}
        </div>
      </div>
    );
  }
  return (
    <div className={styles.intentMsg}>
      <div
        className={[
          styles.msgUser,
          !expanded && intentLong ? styles.intentClamped : "",
          !intent ? styles.intentPlaceholder : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {intent ?? "No instruction prompt available for this agent."}
      </div>
      <div className={styles.intentControls}>
        {intentLong ? (
          <button type="button" className={styles.intentToggle} onClick={() => setExpanded((v) => !v)}>
            {expanded ? "Show less" : "Show more"}
          </button>
        ) : null}
        {onSaveIntent ? (
          <button
            type="button"
            className={styles.intentEdit}
            aria-label="Edit initial intent"
            title="Edit initial intent"
            onClick={startEdit}
          >
            <FontAwesomeIcon icon={faPen} />
          </button>
        ) : null}
      </div>
    </div>
  );
};
