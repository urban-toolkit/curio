import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";

import { AgentRunStatusLine } from "../AgentRunStatusLine";
import styles from "../AgentChatPanel.module.css";

/** The reply hasn't streamed its first delta yet (tool rounds, the blocking
 * fallback): a standalone pending row keeps the live indicator visible at the
 * transcript tail (dev/80 amendment). */
export const PendingReplyRow: React.FC<{ tint: string; startedAt: number }> = ({ tint, startedAt }) => (
  <div className={styles.agentRow}>
    <span className={`${styles.agentRowAvatar} ${tint}`} aria-hidden="true">
      <FontAwesomeIcon icon={faRobot} />
    </span>
    <div className={styles.agentCol}>
      <div className={styles.turnMeta}>
        <AgentRunStatusLine display={{ kind: "running", startedAt }} tintClassName={tint} />
      </div>
    </div>
  </div>
);
