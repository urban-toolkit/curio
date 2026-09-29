import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronLeft, faChevronRight, faRobot, faTrashCan, faXmark } from "@fortawesome/free-solid-svg-icons";

import styles from "../AgentChatPanel.module.css";

/**
 * The ONE dark top header of the opened agent view (DEC-042, dev/21): the
 * master agent identity, the ‹ › agent-cycling arrows, the identification
 * details (attached target + session in the tooltip) and Close — no Pin, no
 * static "Agent Catalog" bar (that chrome is the roster drawer's).
 */
export const ChatHeader: React.FC<{
  tint: string;
  title: React.ReactNode;
  index: number;
  total: number;
  onPrev?: () => void;
  onNext?: () => void;
  onClear?: () => void;
  onClose: () => void;
  targetLabel: string;
  targetTooltip: string;
  titleError: string | null;
}> = ({ tint, title, index, total, onPrev, onNext, onClear, onClose, targetLabel, targetTooltip, titleError }) => (
  // Addressable from outside the CSS-module hash, so the #228 baseline can
  // clip to the header rather than spend its diff budget on an empty
  // transcript (agent-chat-names-its-node).
  <div className={styles.header} data-curio-chat-header="true">
    <div className={styles.headerRow}>
      <button
        type="button"
        className={styles.cycleBtn}
        aria-label="Previous agent"
        title="Previous agent"
        disabled={!onPrev}
        onClick={onPrev}
      >
        <FontAwesomeIcon icon={faChevronLeft} />
      </button>
      <span className={`${styles.headerBot} ${tint}`} aria-hidden="true">
        <FontAwesomeIcon icon={faRobot} />
      </span>
      {title}
      <span className={styles.position}>
        {index} / {total}
      </span>
      <button
        type="button"
        className={styles.cycleBtn}
        aria-label="Next agent"
        title="Next agent"
        disabled={!onNext}
        onClick={onNext}
      >
        <FontAwesomeIcon icon={faChevronRight} />
      </button>
      <span className={styles.headerSpacer} />
      {onClear ? (
        <button
          type="button"
          className={styles.headerBtn}
          aria-label="Clear conversation"
          title="Clear conversation"
          onClick={onClear}
        >
          <FontAwesomeIcon icon={faTrashCan} />
        </button>
      ) : null}
      <button type="button" className={styles.headerBtn} aria-label="Close chat" title="Close chat" onClick={onClose}>
        <FontAwesomeIcon icon={faXmark} />
      </button>
    </div>
    <div className={styles.headerRow}>
      <span className={styles.subtitle} title={targetTooltip}>
        Attached to {targetLabel}
      </span>
      {titleError ? <span className={styles.titleError}>{titleError}</span> : null}
      <span className={styles.headerSpacer} />
    </div>
  </div>
);
