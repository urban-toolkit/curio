import React from "react";
import { DrawerTab } from "./packageTypes";
import styles from "./DrawerTabs.module.css";

export interface DrawerTabsProps {
  tab: DrawerTab;
  installedCount: number;
  onChange: (tab: DrawerTab) => void;
}

/** Tab strip for the Node Catalog drawer: Browse all / In dataflow.
 *
 * There were two more, and neither did anything. "Featured" and "Updates" were
 * rendered and clickable, but the drawer collapsed both onto "browse" before
 * handing the state back (`tab === "featured" || tab === "updates" ? "browse"`)
 * and its list never depended on `tab` at all - so clicking either left the
 * same rows on screen with "Browse all" still painted as the selected tab.
 * "Updates" was the worse of the two: it carried a real accent count, so it
 * invited a click that then did nothing at all.
 *
 * The per-card "update available" line is unaffected - `MyPackagesList` and
 * `PackageCard` compute that themselves from the catalog row.
 */
export const DrawerTabs: React.FC<DrawerTabsProps> = ({
  tab,
  installedCount,
  onChange,
}) => (
  <nav className={styles.tabs} aria-label="Catalog sections">
    <button
      type="button"
      className={`${styles.tab} ${tab === "browse" ? styles.tabActive : ""}`}
      aria-pressed={tab === "browse"}
      onClick={() => onChange("browse")}
    >
      Browse all
    </button>

    <button
      type="button"
      className={`${styles.tab} ${tab === "installed" ? styles.tabActive : ""}`}
      aria-pressed={tab === "installed"}
      onClick={() => onChange("installed")}
    >
      In dataflow
      {installedCount > 0 ? (
        <span className={`${styles.tabBadge} ${styles.tabBadgeDark}`}>{installedCount}</span>
      ) : null}
    </button>
  </nav>
);
