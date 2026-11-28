import React, { useId, useState } from "react";

import ModalShell from "../../../ModalShell";
import dialogStyles from "../../../ConfirmDialog.module.css";
import styles from "../AgentChatPanel.module.css";

/** What the field shows when the agent has no instructions to start from. */
export const NO_INTENT = "No instruction prompt available for this agent.";

/**
 * Edit initial intent, from the chat's More menu: the instructions this
 * chat's agent starts from, in a field with Save and Cancel. Saving an
 * emptied field clears the override, and the agent starts from its own
 * instructions again. Asked on the overlay layer, over the chat panel, as
 * Clear conversation's question is.
 */
export const IntentDialog: React.FC<{
  intent: string | null | undefined;
  onSave: (intent: string | null) => Promise<void>;
  onClose: () => void;
}> = ({ intent, onSave, onClose }) => {
  const titleId = useId();
  const [draft, setDraft] = useState(intent ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(draft.trim() ? draft : null);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save the intent");
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalShell onClose={saving ? () => {} : onClose} titleId={titleId} layer="overlay">
      <form
        className={dialogStyles.dialog}
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <h2 id={titleId} className={dialogStyles.title}>
          Initial intent
        </h2>
        <p className={dialogStyles.bodyText}>What this chat&apos;s agent starts from.</p>
        <textarea
          className={styles.intentTextarea}
          aria-label="Initial intent"
          placeholder={NO_INTENT}
          value={draft}
          disabled={saving}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
        />
        {error ? (
          <p className={styles.intentError} role="alert">
            {error}
          </p>
        ) : null}
        <div className={dialogStyles.footer}>
          <button type="button" className={dialogStyles.ghostButton} disabled={saving} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={dialogStyles.actionButton} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
};
