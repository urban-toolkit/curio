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
 * What an agent at work is doing, for its running dot, or null while it is not
 * at work: *atWork*, its chip's words while it is in the dataflow's room, else
 * its Solve running in the background (dev/115; opening the chat re-attaches).
 * Its badge, its chip in the dock and its entry in the chat's rail all ask
 * this.
 */
export function workingText(attachment: AgentAttachment, atWork: string | null = null): string | null {
  return atWork
    ?? (attachment.liveJob?.status === "running"
      ? `${attachmentDisplayName(attachment)} is solving in the background`
      : null);
}

/** The name of the dot of an agent that waits for you. */
export const WAITS_FOR_YOU = "Waits for you";

/** Whether *attachment*'s agent waits for the user to pick a node's source,
 * as the listing says (`waitsForYou`): a node's Dataset Finder, and the
 * agent whose chat asked for its candidates. Its badge, its chip in the dock
 * and its entry in the chat's rail show the waiting dot. */
export function waitsForYou(attachment: AgentAttachment): boolean {
  return (attachment.waitsForYou ?? []).length > 0;
}

/**
 * What an agent's chip holds: its category's glyph, not the generic robot
 * (several agents can be attached to one canvas, and on the canvas the badge
 * is all there is to tell them apart), while it works the running dot, which
 * *working* labels, and while it waits for you the waiting dot, in the
 * running dot's corner, which moves aside for it.
 */
export function AgentGlyph({
  category,
  working,
  waiting = false,
}: {
  category: string | null | undefined;
  working: string | null;
  waiting?: boolean;
}) {
  return (
    <>
      <FontAwesomeIcon icon={agentCategoryIcon(category)} className={styles.icon} />
      {working ? (
        <span
          className={waiting ? `${styles.runningDot} ${styles.runningDotAside}` : styles.runningDot}
          role="img"
          aria-label={working}
        />
      ) : null}
      {waiting ? <span className={styles.waitingDot} role="img" aria-label={WAITS_FOR_YOU} /> : null}
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
 * While it waits for you to pick a node's source (`waitsForYou`), the waiting
 * dot shows, and its name and tooltip say so.
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
  // runs in the background, or while the agent is at work in the room.
  const working = workingText(attachment, atWork);
  const waiting = waitsForYou(attachment);
  return (
    <div
      className={`${styles.badge} ${active ? styles.badgeActive : ""}`}
      data-tooltip={atWork ?? (waiting ? `${displayName} waits for you` : displayName)}
      data-agent-at-work={atWork ? "true" : undefined}
    >
      <button
        type="button"
        className={`${styles.avatar} ${agentTint(attachment.category)}`}
        aria-label={`Open chat with ${displayName}${waiting ? ", waits for you" : ""}`}
        onClick={(e) => {
          e.stopPropagation();
          onOpen();
        }}
      >
        <AgentGlyph category={attachment.category} working={working} waiting={waiting} />
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
