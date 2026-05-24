import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGripVertical } from "@fortawesome/free-solid-svg-icons";
import { PACKAGE_STAGING_MIME } from "../../../constants/packagePaletteStaging";
import styles from "./PackageStagingDragGrip.module.css";

export interface PackageStagingDragGripProps {
  /** The React-Flow node id — embedded in the drag-transfer payload. */
  nodeId: string;
  /** When `true`, the icon color is inverted to stay legible on dark highlighted nodes. */
  keywordHighlighted: boolean;
}

/**
 * A drag-handle rendered inside a canvas node while the packages palette is in
 * **edit mode**.  Dragging it deposits the node's id (via `PACKAGE_STAGING_MIME`)
 * onto a package-panel drop zone, staging that node kind into the active package.
 */
export function PackageStagingDragGrip({ nodeId, keywordHighlighted }: PackageStagingDragGripProps) {
  return (
    <div
      className={`nodrag nowheel ${styles.grip}`}
      draggable
      title="Drag onto a dashed drop zone in the Packages panel (Edit mode)."
      aria-label="Drag onto a dashed drop zone in the Packages panel when editing packages"
      role="presentation"
      onDragStart={(e) => {
        e.stopPropagation();
        e.dataTransfer.setData(PACKAGE_STAGING_MIME, JSON.stringify({ nodeId }));
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

