import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faThumbtack, faXmark } from "@fortawesome/free-solid-svg-icons";
import { CatalogKindIcon } from "../../catalog/CatalogKindVisuals";
import type { CatalogItemKind } from "../../catalog/CatalogKindVisuals";
import styles from "./DrawerHeader.module.css";

export interface DrawerHeaderProps {
  pinned: boolean;
  onPinToggle: () => void;
  onClose: () => void;
  /** Catalog item kind shown as the type icon. Defaults to the Node catalog. */
  kind?: CatalogItemKind;
  title?: string;
  titleId?: string;
  subtitle?: string;
  closeAriaLabel?: string;
}

/**
 * Top bar + subtitle block shared by the Node Catalog and Data Catalog drawers.
 * Renders the pin/close controls, the drawer title with its kind icon, and a
 * one-line subtitle.
 */
export const DrawerHeader: React.FC<DrawerHeaderProps> = ({
  pinned,
  onPinToggle,
  onClose,
  kind = "package",
  title = "Node catalog",
  titleId = "node-catalog-drawer-title",
  subtitle = "Discover and install nodes that extend Curio.",
  closeAriaLabel = "Close node catalog drawer",
}) => (
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

      <div className={styles.drawerTitleRow}>
        <CatalogKindIcon kind={kind} size="sm" />
        <h2 id={titleId} className={styles.drawerTitle}>
          {title}
        </h2>
      </div>

      <button
        type="button"
        className={styles.iconBtn}
        aria-label={closeAriaLabel}
        onClick={onClose}
      >
        <FontAwesomeIcon icon={faXmark} aria-hidden />
      </button>
    </header>

    <div className={styles.subtitleBlock}>
      <p className={styles.subtitle}>{subtitle}</p>
    </div>
  </>
);
