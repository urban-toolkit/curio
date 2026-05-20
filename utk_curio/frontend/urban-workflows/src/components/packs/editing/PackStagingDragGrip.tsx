import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGripVertical } from "@fortawesome/free-solid-svg-icons";
import { PACK_STAGING_MIME } from "../../../constants/packPaletteStaging";
import styles from "./PackStagingDragGrip.module.css";

export interface PackStagingDragGripProps {
  /** The React-Flow node id — embedded in the drag-transfer payload. */
  nodeId: string;
  /** When `true`, the icon color is inverted to stay legible on dark highlighted nodes. */
  keywordHighlighted: boolean;
}

/**
 * A drag-handle rendered inside a canvas node while the packs palette is in
 * **edit mode**.  Dragging it deposits the node's id (via `PACK_STAGING_MIME`)
 * onto a pack-panel drop zone, staging that node kind into the active pack.
 */
export function PackStagingDragGrip({ nodeId, keywordHighlighted }: PackStagingDragGripProps) {
  return (
    <div
      className={`nodrag nowheel ${styles.grip}`}
      draggable
      title="Drag onto a dashed drop zone in the Packs panel (Edit mode)."
      aria-label="Drag onto a dashed drop zone in the Packs panel when editing packs"
      role="presentation"
      onDragStart={(e) => {
        e.stopPropagation();
        e.dataTransfer.setData(PACK_STAGING_MIME, JSON.stringify({ nodeId }));
        e.dataTransfer.effectAllowed = "copyMove";
      }}
    >
      <FontAwesomeIcon
        icon={faGripVertical}
        className={keywordHighlighted ? styles.iconHighlighted : styles.icon}
      />
    </div>
  );
}

