import React, { memo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleInfo } from "@fortawesome/free-solid-svg-icons";
import styles from "./CopyButton.module.css";

export interface DetailsButtonProps {
  /** What it opens, for the accessible name: "View Bike Routes details". */
  label: string;
  onClick: () => void;
  className?: string;
}

/**
 * "View details" as an icon, for a row too dense to spell it out.
 *
 * The palettes' rows had no way into an item's details at all, while every
 * catalog card offers "View details". This is that control at palette size,
 * drawn exactly like the Copy button beside it so the two read as a pair.
 */
export const DetailsButton = memo(function DetailsButton({
  label,
  onClick,
  className,
}: DetailsButtonProps) {
  return (
    <button
      type="button"
      className={`${styles.root} ${styles.icon} ${className ?? ""}`}
      title={label}
      aria-label={label}
      onClick={(event) => {
        // Rows are clickable themselves: a dataset row selects its nodes.
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
    >
      <FontAwesomeIcon icon={faCircleInfo} aria-hidden />
    </button>
  );
});

export default DetailsButton;
