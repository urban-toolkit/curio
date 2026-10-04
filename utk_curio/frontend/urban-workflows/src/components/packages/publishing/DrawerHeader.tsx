import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faThumbtack, faXmark } from "@fortawesome/free-solid-svg-icons";
import { CatalogKindIcon } from "../../catalog/CatalogKindVisuals";
import type { CatalogItemKind } from "../../catalog/CatalogKindVisuals";
import styles from "./DrawerHeader.module.css";

export interface DrawerHeaderProps {
  pinned?: boolean;
  /** Renders the pin button. The catalog drawers pin; API Settings and
   *  Monitor do not. */
  onPinToggle?: () => void;
  onClose: () => void;
  /** Catalog item kind shown as the type icon. Defaults to the Node Catalog;
   *  null shows no icon. */
  kind?: CatalogItemKind | null;
  title?: string;
  titleId?: string;
  /** null shows no subtitle block. */
  subtitle?: string | null;
  closeAriaLabel?: string;
  /** Extra controls between the title and the close button. Rendered only
   *  when given, so the Node and Data drawers are unchanged. */
  actions?: React.ReactNode;
}

/**
 * Top bar + subtitle block shared by the canvas drawers. Renders the pin/close
 * controls, the drawer title with its kind icon, and a one-line subtitle.
 */
export const DrawerHeader: React.FC<DrawerHeaderProps> = ({
  pinned = false,
  onPinToggle,
  onClose,
  kind = "package",
  title = "Node Catalog",
  titleId = "node-catalog-drawer-title",
  subtitle = "Node packages available in this project.",
  closeAriaLabel = "Close Node Catalog drawer",
  actions,
}) => (
  <>
    <header className={styles.topBar}>
      {onPinToggle ? (
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
      ) : null}

      <div className={styles.drawerTitleRow}>
        {kind ? <CatalogKindIcon kind={kind} size="sm" /> : null}
        <h2 id={titleId} className={styles.drawerTitle}>
          {title}
        </h2>
      </div>

      {actions}

      <button
        type="button"
        className={styles.iconBtn}
        aria-label={closeAriaLabel}
        onClick={onClose}
      >
        <FontAwesomeIcon icon={faXmark} aria-hidden />
      </button>
    </header>

    {subtitle ? (
      <div className={styles.subtitleBlock}>
        <p className={styles.subtitle}>{subtitle}</p>
      </div>
    ) : null}
  </>
);
