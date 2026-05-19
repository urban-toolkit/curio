import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faThumbtack, faXmark } from "@fortawesome/free-solid-svg-icons";
import styles from "./DrawerHeader.module.css";

export interface DrawerHeaderProps {
  pinned: boolean;
  onPinToggle: () => void;
  onClose: () => void;
}

/**
 * Top bar + subtitle block for the Node Warehouse drawer.
 * Renders the pin/close controls, the drawer title, a one-line subtitle,
 * and the "compatible with this workspace" pill.
 */
export const DrawerHeader: React.FC<DrawerHeaderProps> = ({ pinned, onPinToggle, onClose }) => (
  <>
    <header className={styles.topBar}>
      <button
        type="button"
        className={`${styles.iconBtn} ${pinned ? styles.iconBtnActive : ""}`}
        aria-label={pinned ? "Unpin drawer" : "Pin drawer open"}
        aria-pressed={pinned}
        title={pinned ? "Unpin drawer" : "Pin drawer (scrim won't close)"}
        onClick={onPinToggle}
      >
        <FontAwesomeIcon icon={faThumbtack} aria-hidden />
      </button>

      <h2 id="node-warehouse-drawer-title" className={styles.drawerTitle}>
        Node warehouse
      </h2>

      <button
        type="button"
        className={styles.iconBtn}
        aria-label="Close node warehouse drawer"
        onClick={onClose}
      >
        <FontAwesomeIcon icon={faXmark} aria-hidden />
      </button>
    </header>

    <div className={styles.subtitleBlock}>
      <p className={styles.subtitle}>Discover and install nodes that extend Curio.</p>
      <span className={styles.compatPill}>
        <span className={styles.compatDot} aria-hidden />
        Compatible with this Curio workspace
      </span>
    </div>
  </>
);

