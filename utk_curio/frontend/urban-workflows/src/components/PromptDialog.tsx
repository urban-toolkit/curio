import React, { useId, useState } from "react";
import ModalShell from "./ModalShell";
import styles from "./ConfirmDialog.module.css";

export interface PromptDialogProps {
  title: string;
  /** Label for the text field, e.g. "Name". */
  fieldLabel: string;
  initialValue?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  busy?: boolean;
  /** Called with the trimmed value. Never called with an empty string. */
  onConfirm: (value: string) => void;
  onCancel: () => void;
}

/** The app's replacement for `window.prompt` (#197).
 *
 * Shares ConfirmDialog's stylesheet and the same ModalShell contract; only the
 * body differs, being a single text field. Submitting is a real `<form>` so
 * Enter commits, matching what the native prompt did.
 */
export default function PromptDialog({
  title,
  fieldLabel,
  initialValue = "",
  confirmLabel = "Save",
  cancelLabel = "Cancel",
  busy = false,
  onConfirm,
  onCancel,
}: PromptDialogProps) {
  const titleId = useId();
  const fieldId = useId();
  const [value, setValue] = useState(initialValue);
  const trimmed = value.trim();

  return (
    <ModalShell onClose={busy ? () => {} : onCancel} titleId={titleId}>
      <form
        className={styles.dialog}
        onSubmit={(e) => {
          e.preventDefault();
          if (!trimmed || busy) return;
          onConfirm(trimmed);
        }}
      >
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        <div className={styles.field}>
          <label className={styles.fieldLabel} htmlFor={fieldId}>
            {fieldLabel}
          </label>
          <input
            id={fieldId}
            className={styles.input}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={busy}
            autoFocus
          />
        </div>
        <div className={styles.footer}>
          <button
            type="button"
            className={styles.ghostButton}
            onClick={onCancel}
            disabled={busy}
          >
            {cancelLabel}
          </button>
          <button
            type="submit"
            className={styles.actionButton}
            disabled={busy || !trimmed}
          >
            {confirmLabel}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
