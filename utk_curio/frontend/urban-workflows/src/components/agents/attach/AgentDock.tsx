import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";
import type { AgentAttachment } from "../../../api/agentsApi";
import styles from "./AgentDock.module.css";

/**
 * Presentational dock: a tile per attached agent. Clicking a tile selects it
 * (opens its chat); the ✕ detaches it. Renders nothing when there are none.
 */
export const AgentDock: React.FC<{
  attachments: AgentAttachment[];
  selectedId: string | null;
  onSelect: (attachmentId: string) => void;
  onDetach: (attachmentId: string) => void;
}> = ({ attachments, selectedId, onSelect, onDetach }) => {
  if (attachments.length === 0) return null;
  return (
    <div className={styles.dock} role="toolbar" aria-label="Attached agents">
      {attachments.map((a) => (
        <div
          key={a.attachmentId}
          className={`${styles.tile} ${selectedId === a.attachmentId ? styles.tileActive : ""}`}
          role="button"
          tabIndex={0}
          onClick={() => onSelect(a.attachmentId)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onSelect(a.attachmentId);
          }}
          title={a.coord}
        >
          <FontAwesomeIcon icon={faRobot} className={styles.tileIcon} />
          <span className={styles.tileName}>{a.name}</span>
          <button
            type="button"
            className={styles.detach}
            aria-label={`Detach ${a.name}`}
            onClick={(e) => {
              e.stopPropagation();
              onDetach(a.attachmentId);
            }}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
};
