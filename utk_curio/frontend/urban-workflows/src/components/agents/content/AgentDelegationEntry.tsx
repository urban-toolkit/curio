import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";
import type { AgentDelegationPart } from "../../../services/agents";
import { agentCategoryKey } from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import styles from "./AgentDelegationEntry.module.css";

/**
 * A task this agent handed to another, on its turn (memo dev/72), in one
 * line: the agent it asked, by name, then the task's one-line outcome. The
 * name opens that agent's chat, where the full story lives (the task, its
 * record, its replies). A task that failed says so. What ran it, the
 * capability, the model and its status, is shown only with Show run details.
 *
 * The link is best-effort by contract: no home (`attachmentId: null`) or a
 * since-detached home renders the same entry without a link, never a dead
 * button. Everything shown is bounded server-side and rendered inert.
 */
export const AgentDelegationEntry: React.FC<{
  part: AgentDelegationPart;
  /** Opens the delegated agent's chat; omitted → the entry renders inert. */
  onOpenChat?: (attachmentId: string) => void;
  /** Existence check against the live attachments list (stale-home guard). */
  delegateExists?: (attachmentId: string) => boolean;
  /** The viewer shows run details: the capability, the model and the status. */
  runDetails?: boolean;
}> = ({ part, onOpenChat, delegateExists, runDetails = false }) => {
  const linkable = Boolean(
    part.attachmentId &&
      onOpenChat &&
      (delegateExists ? delegateExists(part.attachmentId) : true),
  );
  const tint = styles[`tint_${agentCategoryKey(part.category)}` as keyof typeof styles];
  const failed = part.status === "failed";
  const model = part.model ? (part.llmLabel ? `${part.llmLabel} (${part.model})` : part.model) : null;
  return (
    <div
      className={`${styles.entry} ${failed ? styles.failed : ""}`}
      role="group"
      aria-label={`Delegated task: ${part.capability}`}
    >
      <span className={`${styles.badge} ${tint}`} aria-hidden="true">
        <FontAwesomeIcon icon={faRobot} />
      </span>
      <div className={styles.line}>
        {linkable ? (
          <button
            type="button"
            className={styles.name}
            aria-label={`Open ${part.name}'s chat`}
            data-tooltip={`Open ${part.name}'s chat`}
            onClick={() => onOpenChat!(part.attachmentId!)}
          >
            {part.name}
          </button>
        ) : (
          <span className={styles.nameText}>{part.name}</span>
        )}
        {part.summary ? <span className={styles.summary}>{part.summary}</span> : null}
        {failed ? <span className={styles.statusFailed}>failed</span> : null}
      </div>
      {runDetails ? (
        <div className={styles.details} data-curio-run-details="">
          {[part.capability, model, failed ? "failed" : "ok"].filter(Boolean).join(" · ")}
        </div>
      ) : null}
    </div>
  );
};
