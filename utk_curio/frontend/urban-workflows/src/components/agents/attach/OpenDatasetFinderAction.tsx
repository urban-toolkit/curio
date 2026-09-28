import React from "react";
import type { AgentRemedy } from "../../../api/agentsApi";
import styles from "../../connectionKeys/AddKeyAction.module.css";

/**
 * dev/126: the ONE rendering of a `dataset-selection` remedy — the twin of
 * dev/116's AddKeyAction. A data-loading node whose source is with the user
 * carries this: its own Dataset Finder holds the candidates, and this button
 * opens that chat. Renders nothing without an attachment to open or a way to
 * open it, so a payload from an older backend degrades to the reason line.
 */
export const OpenDatasetFinderAction: React.FC<{
  remedy?: AgentRemedy | null;
  onOpenChat?: (attachmentId: string) => void;
  /** The node's title or goal, so the button's name says WHICH node. */
  nodeLabel?: string;
  className?: string;
}> = ({ remedy, onOpenChat, nodeLabel, className }) => {
  if (!remedy || remedy.kind !== "dataset-selection") return null;
  const attachmentId = remedy.attachmentId;
  if (!attachmentId || !onOpenChat) return null;
  const label = (nodeLabel ?? "").trim();
  return (
    <button
      type="button"
      className={`${styles.button}${className ? ` ${className}` : ""}`}
      aria-label={
        label ? `Open Dataset Finder for ${label}` : "Open Dataset Finder for this node"
      }
      title="Opens this node's Dataset Finder chat, where the candidates await your selection. Confirm one, then Solve again."
      onClick={() => onOpenChat(attachmentId)}
    >
      Open Dataset Finder{label ? ` for ${label}` : ""}
    </button>
  );
};
