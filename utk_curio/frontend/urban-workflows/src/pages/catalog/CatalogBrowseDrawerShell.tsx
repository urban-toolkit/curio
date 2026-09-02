import React, { useLayoutEffect } from "react";
import styles from "./CatalogBrowseLayout.module.css";

export interface CatalogBrowseDrawerShellProps {
  /** True while a catalog item is selected and its detail should be visible. */
  presented: boolean;
  /** Called when the drawer grid slot should expand (true) or collapse (false). */
  onLayoutChange?: (slotOpen: boolean) => void;
  children: React.ReactNode;
}

/**
 * Shared right-hand detail drawer for the catalog browse pages. The drawer
 * column and the page grid appear and disappear together, with no motion — the
 * pages auto-select their first item, so any enter transition replayed on every
 * Nodes/Data tab switch.
 */
export const CatalogBrowseDrawerShell: React.FC<CatalogBrowseDrawerShellProps> = ({
  presented,
  onLayoutChange,
  children,
}) => {
  useLayoutEffect(() => {
    onLayoutChange?.(presented);
  }, [presented, onLayoutChange]);

  if (!presented) return null;

  return (
    <div className={styles.browseDrawerColumn}>
      {/* CSS-module class names are hashed in a production build, so a test
          cannot target this panel by class. Every catalog shares this shell,
          so one hook covers all of them. */}
      <aside className={styles.browseDrawer} data-curio-browse-drawer="true">
        {children}
      </aside>
    </div>
  );
};

export default CatalogBrowseDrawerShell;
