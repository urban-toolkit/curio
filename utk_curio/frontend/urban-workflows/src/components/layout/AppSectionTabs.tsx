import React from "react";
import clsx from "clsx";
import { NavLink } from "react-router-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

import { CATALOG_KIND_META } from "../catalog/CatalogKindVisuals";
import { CATALOG_SECTIONS, PROJECTS_SECTION, type AppSection } from "./catalogSections";
import headerStyles from "./GlobalPageHeader.module.css";
import styles from "./AppSectionTabs.module.css";

function SectionLink({ section }: { section: AppSection }) {
  return (
    <NavLink
      to={section.path}
      end={section.end}
      className={({ isActive }) =>
        clsx(headerStyles.barButton, isActive && headerStyles.barButtonActive, isActive && styles.sectionCurrent)
      }
      aria-label={section.name}
      data-tooltip={section.name}
    >
      <FontAwesomeIcon icon={CATALOG_KIND_META[section.kind].icon} className={headerStyles.barIcon} />
      <span className={styles.sectionLabel}>{section.shortName}</span>
    </NavLink>
  );
}

/**
 * The app's top-level sections, in the top bar of every section page (Projects,
 * the catalogs, Monitor, API Settings), drawn as the canvas draws its catalog
 * buttons: a glyph and a short name, the full name its accessible name and its
 * tooltip. They link to the pages; the canvas's buttons open the drawers.
 *
 * aria-label is "Main sections", not "Catalog sections" — the latter is taken
 * by components/packages/publishing/DrawerTabs.tsx, and a duplicate makes
 * unscoped get_by_role("navigation", ...) lookups strict-mode ambiguous.
 */
export function AppSectionTabs() {
  return (
    <nav className={styles.sections} aria-label="Main sections">
      <SectionLink section={PROJECTS_SECTION} />
      <span className={headerStyles.divider} aria-hidden />
      {CATALOG_SECTIONS.map((section) => (
        <SectionLink key={section.kind} section={section} />
      ))}
    </nav>
  );
}

export default AppSectionTabs;
