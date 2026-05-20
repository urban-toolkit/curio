import React from "react";
import { DrawerTab } from "./packTypes";
import styles from "./DrawerTabs.module.css";

export interface DrawerTabsProps {
  tab: DrawerTab;
  installedCount: number;
  updateCount: number;
  onChange: (tab: DrawerTab) => void;
}

/** Tab strip that lets users switch between Featured / Browse / Installed / Updates views. */
export const DrawerTabs: React.FC<DrawerTabsProps> = ({
  tab,
  installedCount,
  updateCount,
  onChange,
}) => (
  <nav className={styles.tabs} aria-label="Warehouse sections">
    <button
      type="button"
      className={`${styles.tab} ${tab === "featured" ? styles.tabActive : ""}`}
      onClick={() => onChange("featured")}
    >
      Featured
    </button>

    <button
      type="button"
      className={`${styles.tab} ${tab === "browse" ? styles.tabActive : ""}`}
      onClick={() => onChange("browse")}
    >
      Browse all
    </button>

    <button
      type="button"
      className={`${styles.tab} ${tab === "installed" ? styles.tabActive : ""}`}
      onClick={() => onChange("installed")}
    >
      Installed
      {installedCount > 0 ? (
        <span className={`${styles.tabBadge} ${styles.tabBadgeDark}`}>{installedCount}</span>
      ) : null}
    </button>

    <button
      type="button"
      className={`${styles.tab} ${tab === "updates" ? styles.tabActive : ""} ${
        updateCount === 0 ? styles.tabMuted : ""
      }`}
      onClick={() => onChange("updates")}
    >
      Updates
      {updateCount > 0 ? (
        <span className={`${styles.tabBadge} ${styles.tabBadgeAccent}`}>{updateCount}</span>
      ) : null}
    </button>
  </nav>
);

