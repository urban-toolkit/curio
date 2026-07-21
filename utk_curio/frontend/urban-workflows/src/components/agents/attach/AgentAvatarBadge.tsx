import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";
import type { AgentAttachment } from "../../../api/agentsApi";
import { agentCategoryKey } from "../../menus/nodes/agentsPalette/agentCategoryStyle";
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
  const tint =
    styles[`tint_${agentCategoryKey(attachment.category)}` as keyof typeof styles] ??
    styles.tint_default;
  return (
    <div className={`${styles.badge} ${active ? styles.badgeActive : ""}`}>
      <button
        type="button"
        className={`${styles.avatar} ${tint}`}
        title={`${attachment.name} — open chat`}
        aria-label={`Open chat with ${attachment.name}`}
        onClick={(e) => {
          e.stopPropagation();
          onOpen();
        }}
      >
        <FontAwesomeIcon icon={faRobot} className={styles.icon} />
      </button>
      <button
        type="button"
        className={styles.detach}
        aria-label={`Detach ${attachment.name}`}
        onClick={(e) => {
          e.stopPropagation();
          onDetach();
        }}
      >
        ✕
      </button>
    </div>
  );
};
