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
      {/* The identity attribute the catalog PAGES' detail drawer was missing.
          Its three canvas peers each carry one (`data-curio-agent-catalog-drawer`
          and friends), but this shared shell had only hashed module classes - and
          `aside` matches the filter sidebar too, so a test had no honest way to
          address the drawer. Same job as `data-agent-coord` on the cards. */}
      <aside className={styles.browseDrawer} data-curio-browse-drawer="true">
        {children}
      </aside>
    </div>
  );
};

export default CatalogBrowseDrawerShell;
