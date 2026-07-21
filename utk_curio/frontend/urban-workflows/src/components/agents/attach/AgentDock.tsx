import React from "react";
import type { AgentAttachment } from "../../../api/agentsApi";
import { AgentAvatarBadge } from "./AgentAvatarBadge";
import styles from "./AgentDock.module.css";

/**
 * Canvas-agent dock: the same avatar chips as the node badges (per the
 * concept), clustered in a persistent bar centered at the bottom of the canvas.
 * Clicking an avatar opens its chat; the hover ✕ detaches. Renders nothing when
 * there are no canvas agents.
 */
export const AgentDock: React.FC<{
  attachments: AgentAttachment[];
  selectedId: string | null;
  onSelect: (attachmentId: string) => void;
  onDetach: (attachmentId: string) => void;
}> = ({ attachments, selectedId, onSelect, onDetach }) => {
  if (attachments.length === 0) return null;
  return (
    <div className={styles.dock} role="toolbar" aria-label="Canvas agents">
      {attachments.map((a) => (
        <AgentAvatarBadge
          key={a.attachmentId}
          attachment={a}
          active={selectedId === a.attachmentId}
          onOpen={() => onSelect(a.attachmentId)}
          onDetach={() => onDetach(a.attachmentId)}
        />
      ))}
    </div>
  );
};
