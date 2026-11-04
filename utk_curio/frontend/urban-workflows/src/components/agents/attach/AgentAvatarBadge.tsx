import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { attachmentDisplayName, type AgentAttachment } from "../../../services/agents";
import {
  agentCategoryIcon,
  agentCategoryKey,
} from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import styles from "./AgentAvatarBadge.module.css";

/** The class that tints an agent's chip in its category's color: its badge's,
 *  and its chip's among the people in the canvas's dock. */
export function agentTint(category: string | null | undefined): string {
  return styles[`tint_${agentCategoryKey(category)}` as keyof typeof styles];
}

/**
 * What an agent's chip holds: its category's glyph, not the generic robot
 * (several agents can be attached to one canvas, and on the canvas the badge
 * is all there is to tell them apart), and while it works the running dot,
 * which *working* labels.
 */
export function AgentGlyph({ category, working }: { category: string | null | undefined; working: string | null }) {
  return (
    <>
      <FontAwesomeIcon icon={agentCategoryIcon(category)} className={styles.icon} />
      {working ? <span className={styles.runningDot} role="img" aria-label={working} /> : null}
    </>
  );
}

/**
 * A single attached-agent avatar: a category-tinted robot chip that opens the
 * agent's chat on click and detaches via a hover ✕. Shared by the node badges
 * and the canvas dock so both render identically (per the concept). Its name
 * is the badge's tooltip, the one Curio tooltip, the same size at any zoom.
 *
 * While the agent is at work in the dataflow's room (`atWork`, what its chip
 * among the people says), the tooltip says what it is doing and the running
 * dot shows, as on its chip in the row: a canvas agent keeps this one chip.
 */
export const AgentAvatarBadge: React.FC<{
  attachment: AgentAttachment;
  active: boolean;
  onOpen: () => void;
  onDetach: () => void;
  /** What the agent at work is doing, "Dataflow Builder (asked by Ana),
   *  using catalogs"; null while it is not at work. */
  atWork?: string | null;
}> = ({ attachment, active, onOpen, onDetach, atWork = null }) => {
  // "<name>: <title>" once the conversation is titled (memo dev/25), so
  // multiple instances of the same template stay distinguishable.
  const displayName = attachmentDisplayName(attachment);
  // dev/115 (docs/11:178): the dock's running dot, while this agent's Solve
  // runs in the background (opening the chat re-attaches), or while the agent
  // is at work in the room.
  const working = atWork
    ?? (attachment.liveJob?.status === "running" ? `${displayName} is solving in the background` : null);
  return (
    <div
      className={`${styles.badge} ${active ? styles.badgeActive : ""}`}
      data-tooltip={atWork ?? displayName}
      data-agent-at-work={atWork ? "true" : undefined}
    >
      <button
        type="button"
        className={`${styles.avatar} ${agentTint(attachment.category)}`}
        aria-label={`Open chat with ${displayName}`}
        onClick={(e) => {
          e.stopPropagation();
          onOpen();
        }}
      >
        <AgentGlyph category={attachment.category} working={working} />
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
    </div>
  );
};
