import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";
import type { AgentAttachment } from "../../../api/agentsApi";
import {
  agentCategoryIcon,
  agentCategoryKey,
} from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import { attachmentDisplayName } from "./attachmentDisplayName";
import styles from "./AgentAvatarBadge.module.css";

/**
 * A single attached-agent avatar: a category-tinted robot chip that opens the
 * agent's chat on click and detaches via a hover ✕. Shared by the node badges
 * and the canvas dock so both render identically (per the concept).
 */
export const AgentAvatarBadge: React.FC<{
  attachment: AgentAttachment;
  active: boolean;
  onOpen: () => void;
  onDetach: () => void;
}> = ({ attachment, active, onOpen, onDetach }) => {
  const tint = styles[`tint_${agentCategoryKey(attachment.category)}` as keyof typeof styles];
  // "<name>: <title>" once the conversation is titled (memo dev/25), so
  // multiple instances of the same template stay distinguishable.
  const displayName = attachmentDisplayName(attachment);
  return (
    <div className={`${styles.badge} ${active ? styles.badgeActive : ""}`}>
      <button
        type="button"
        className={`${styles.avatar} ${tint}`}
        aria-label={`Open chat with ${displayName}`}
        onClick={(e) => {
          e.stopPropagation();
          onOpen();
        }}
      >
        {/* The category glyph, not the generic robot: several agents can be
            attached to one canvas, and on the canvas the badge is all there
            is to tell them apart. */}
        <FontAwesomeIcon icon={agentCategoryIcon(attachment.category)} className={styles.icon} />
        {attachment.liveJob?.status === "running" ? (
          // dev/115 (docs/11:178): the dock's running dot — this agent's Solve
          // is running in the background; opening the chat re-attaches.
          <span
            className={styles.runningDot}
            role="img"
            aria-label={`${displayName} is solving in the background`}
          />
        ) : null}
      </button>
      <button
        type="button"
        className={styles.detach}
        aria-label={`Detach ${displayName}`}
        onClick={(e) => {
          e.stopPropagation();
          onDetach();
        }}
      >
        ✕
      </button>
      {/* macOS Dock-style name label, shown below the chip on hover. */}
      <span className={styles.tooltip} aria-hidden="true">
        {displayName}
      </span>
    </div>
  );
};
