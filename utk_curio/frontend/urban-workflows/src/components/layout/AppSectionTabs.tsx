import React from "react";
import { NavLink } from "react-router-dom";
import styles from "./AppSectionTabs.module.css";

function tabClassName({ isActive }: { isActive: boolean }): string {
  return [styles.tabLink, isActive ? styles.tabLinkActive : ""].filter(Boolean).join(" ");
}

/**
 * The app's top-level sections, as sibling tabs. Rendered under
 * GlobalPageHeader on both /projects and /catalog/* so the two read as peers
 * instead of pointing at each other through one-off header buttons.
 *
 * aria-label is "Main sections", not "Catalog sections" — the latter is taken
 * by components/packages/publishing/DrawerTabs.tsx, and a duplicate makes
 * unscoped get_by_role("navigation", ...) lookups strict-mode ambiguous.
 */
export function AppSectionTabs() {
  return (
    <nav className={styles.tabBar} aria-label="Main sections">
      <NavLink to="/projects" className={tabClassName} end>
        Projects
      </NavLink>
      <NavLink to="/catalog/nodes" className={tabClassName} end>
        Node Catalog
      </NavLink>
      {/* No `end`: /catalog/data/:datasetId keeps this tab active. */}
      <NavLink to="/catalog/data" className={tabClassName}>
        Data Catalog
      </NavLink>
      <NavLink to="/catalog/agents" className={tabClassName} end>
        Agent Catalog
      </NavLink>
    </nav>
  );
}

export default AppSectionTabs;
