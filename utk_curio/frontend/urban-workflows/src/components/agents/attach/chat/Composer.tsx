import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faArrowUp } from "@fortawesome/free-solid-svg-icons";

import styles from "../AgentChatPanel.module.css";

/** The pill composer (memo dev/77): a one-row textarea that grows with content
 * (the caller's auto-grow ref), Enter sends, Shift+Enter falls through to the
 * native newline, an in-flight IME composition's commit-Enter never sends. */
export const Composer: React.FC<{
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}> = ({ value, onChange, onSend, busy, textareaRef }) => (
  <div className={styles.footer}>
    <textarea
      ref={textareaRef}
      className={styles.input}
      value={value}
      rows={1}
      aria-label="Message this agent"
      placeholder="Message this agent…"
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
          e.preventDefault();
          onSend();
        }
      }}
    />
    <button
      type="button"
      className={styles.send}
      aria-label="Send"
      title="Send"
      disabled={busy || !value.trim()}
      onClick={onSend}
    >
      {busy ? "…" : <FontAwesomeIcon icon={faArrowUp} />}
    </button>
  </div>
);
