import React from "react";
import type { AgentRemedy } from "../../../services/agents";
import styles from "../../connectionKeys/AddKeyAction.module.css";

/**
 * dev/126: the ONE rendering of a `dataset-selection` remedy, the twin of
 * dev/116's AddKeyAction. A data-loading node whose source is with the user
 * carries this: its own agent that finds its datasets holds the candidates,
 * and this button opens that chat, named as that agent's manifest names it.
 * Renders nothing without an attachment to open or a way to open it, so a
 * payload from an older backend degrades to the reason line.
 */
export const OpenDatasetFinderAction: React.FC<{
  remedy?: AgentRemedy | null;
  onOpenChat?: (attachmentId: string) => void;
  /** The name of the agent that holds the candidates. Without one, the
   * button says what it opens. */
  agentName?: string | null;
  /** The node's title or goal, so the button's name says WHICH node. */
  nodeLabel?: string;
  className?: string;
}> = ({ remedy, onOpenChat, agentName, nodeLabel, className }) => {
  if (!remedy || remedy.kind !== "dataset-selection") return null;
  const attachmentId = remedy.attachmentId;
  if (!attachmentId || !onOpenChat) return null;
  const label = (nodeLabel ?? "").trim();
  const name = (agentName ?? "").trim();
  const opens = name || "the candidates";
  return (
    <button
      type="button"
      className={`${styles.button}${className ? ` ${className}` : ""}`}
      aria-label={`Open ${opens} for ${label || "this node"}`}
      data-tooltip={
        name
          ? `Opens this node's ${name} chat, where the candidates await your selection. Confirm one, then Solve again.`
          : "Opens the chat where this node's candidates await your selection. Confirm one, then Solve again."
      }
      onClick={() => onOpenChat(attachmentId)}
    >
      Open {opens}{label ? ` for ${label}` : ""}
    </button>
  );
};
