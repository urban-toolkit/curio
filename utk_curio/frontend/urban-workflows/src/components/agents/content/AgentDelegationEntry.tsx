import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";
import type { AgentDelegationPart } from "../../../api/agentsApi";
import { agentCategoryKey } from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import styles from "./AgentDelegationEntry.module.css";

/**
 * The compact delegation entry (memo dev/72): one delegated task on the
 * PARENT's turn — the task title with the delegated agent's icon notched
 * into its corner, a status chip, and the one-line outcome summary. The
 * full story (framed task turn, trace card, execution record) lives in the
 * delegated agent's OWN chat; clicking the icon opens it.
 *
 * The link is best-effort by contract: no home (`attachmentId: null`) or a
 * since-detached home renders the same entry without a link — never a dead
 * button. Everything shown is bounded server-side and rendered inert.
 */
export const AgentDelegationEntry: React.FC<{
  part: AgentDelegationPart;
  /** Opens the delegated agent's chat; omitted → the entry renders inert. */
  onOpenChat?: (attachmentId: string) => void;
  /** Existence check against the live attachments list (stale-home guard). */
  delegateExists?: (attachmentId: string) => boolean;
}> = ({ part, onOpenChat, delegateExists }) => {
  const linkable = Boolean(
    part.attachmentId &&
      onOpenChat &&
      (delegateExists ? delegateExists(part.attachmentId) : true),
  );
  const tint = styles[`tint_${agentCategoryKey(part.category)}` as keyof typeof styles];
  const failed = part.status === "failed";
  return (
    <div
      className={`${styles.entry} ${failed ? styles.failed : ""}`}
      role="group"
      aria-label={`Delegated task: ${part.capability}`}
    >
      {linkable ? (
        <button
          type="button"
          className={`${styles.badge} ${tint}`}
          aria-label={`Open ${part.name}'s chat`}
          title={`Open ${part.name}'s chat`}
          onClick={() => onOpenChat!(part.attachmentId!)}
        >
          <FontAwesomeIcon icon={faRobot} />
        </button>
      ) : (
        <span className={`${styles.badge} ${tint}`} aria-hidden="true">
          <FontAwesomeIcon icon={faRobot} />
        </span>
      )}
      <div className={styles.head}>
        <span className={styles.title}>{part.capability}</span>
        <span className={styles.name}>{part.name}</span>
        <span className={`${styles.status} ${failed ? styles.statusFailed : styles.statusOk}`}>
          {failed ? "failed" : "ok"}
        </span>
      </div>
      {part.summary ? <div className={styles.summary}>{part.summary}</div> : null}
    </div>
  );
};
