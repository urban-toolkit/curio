import React from "react";

import { TITLE_MAX_CHARS } from "../../../../services/agents";
import styles from "../AgentChatPanel.module.css";
import type { ConversationTitleState } from "./useConversationTitle";

/** The header's title cluster: the inline rename input while editing, the
 * click-to-rename button when a rename is possible, a plain label otherwise.
 * No edit icon — the affordance is the title itself (memo dev/25). */
export const ConversationTitle: React.FC<{
  agentName: string;
  displayName: string;
  editable: boolean;
  title: ConversationTitleState;
}> = ({ agentName, displayName, editable, title }) =>
  title.editing ? (
    <span className={`${styles.title} ${styles.titleEditing}`}>
      <span className={styles.titlePrefix}>{agentName}: </span>
      <input
        ref={title.inputRef}
        className={styles.titleInput}
        aria-label="Conversation title"
        maxLength={TITLE_MAX_CHARS}
        value={title.draft}
        onChange={(e) => title.setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            title.finish(true);
          } else if (e.key === "Escape") {
            e.stopPropagation();
            title.finish(false);
          }
        }}
        onBlur={() => title.finish(true)}
      />
    </span>
  ) : editable ? (
    <button
      type="button"
      ref={title.buttonRef}
      className={`${styles.title} ${styles.titleButton}`}
      aria-label="Rename conversation title"
      title="Click to rename"
      onClick={title.start}
    >
      {displayName}
    </button>
  ) : (
    <span className={styles.title}>{displayName}</span>
  );
