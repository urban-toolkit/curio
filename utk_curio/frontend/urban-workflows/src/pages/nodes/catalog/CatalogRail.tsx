import React from "react";
import { CATEGORY_LABELS, Tab } from "./catalogTypes";
import styles from "./Catalog.module.css";

export interface CatalogRailProps {
  tab: Tab;
  onChange: (tab: Tab) => void;
}

/**
 * Left-side category filter rail.
 * Renders a button for each tab defined in CATEGORY_LABELS.
 */
export const CatalogRail: React.FC<CatalogRailProps> = ({ tab, onChange }) => (
  <aside className={styles.rail} aria-label="Category filter">
    <h2 className={styles.railTitle}>Browse</h2>
    {(Object.keys(CATEGORY_LABELS) as Tab[]).map((t) => (
      <button
        key={t}
        type="button"
        className={t === tab ? styles.railItemActive : styles.railItem}
        aria-current={t === tab ? "page" : undefined}
        onClick={() => onChange(t)}
      >
        {CATEGORY_LABELS[t]}
      </button>
    ))}
  </aside>
);

