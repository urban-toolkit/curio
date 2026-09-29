import React from "react";

import styles from "../AgentChatPanel.module.css";

/** The newest turn's alternative prompts as chips (memo dev/39, docs/08);
 * a click puts the chip's text in the composer. */
export const SuggestedPromptsRow: React.FC<{
  alternatives: string[];
  onPick: (prompt: string) => void;
}> = ({ alternatives, onPick }) => (
  <div className={styles.suggestedRow} role="group" aria-label="Suggested prompts">
    <span className={styles.suggestedLabel}>Suggested prompts</span>
    {alternatives.map((alt, i) => (
      <button key={i} type="button" className={styles.suggestedChip} title={alt} onClick={() => onPick(alt)}>
        {alt}
      </button>
    ))}
  </div>
);
