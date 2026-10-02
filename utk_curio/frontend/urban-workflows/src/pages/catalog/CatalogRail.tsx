/**
 * The left rail of every browse page: the four catalogs and /projects.
 *
 * One component, so the five rails cannot drift apart again. They had: some
 * sections opened with an "All formats" or "All categories" row and others did
 * not, the Data Lake page kept its total inside "By provider", the Projects
 * rail had an unlabelled first group the others did not, and zero-count rows
 * showed on one page and not on the next.
 *
 * The shape is the Projects rail's:
 * - an unlabelled top group: "All <items>" with the total, which clears every
 *   filter, then the page's scope row ("In all projects", "Your dataflows")
 *   where it has one;
 * - one labelled section per facet, each after a divider. A row toggles: click
 *   it to filter, click it again to clear it. A row with nothing in it is
 *   hidden unless it is the selected one, so a search cannot strand the
 *   selection out of sight.
 *
 * A row carries a dot only where the cards are coloured by that facet (a
 * dataset's format, a package's or an agent's category), so the dot is the key
 * to the card strips beside it.
 */
import React from "react";

import styles from "./CatalogBrowseLayout.module.css";

export interface CatalogRailRow {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}

export interface CatalogRailEntry extends CatalogRailRow {
  /** What the row filters on, when it differs from its label. */
  value?: string;
  /** A class from CatalogBrowseLayout.module.css that colours the row's dot. */
  dotClassName?: string;
}

export interface CatalogRailSection {
  key: string;
  label: string;
  entries: CatalogRailEntry[];
}

export interface CatalogRailProps {
  ariaLabel: string;
  all: CatalogRailRow;
  scope?: CatalogRailRow;
  sections: CatalogRailSection[];
}

/** The sections as the rail shows them: empty rows and empty sections dropped. */
export function visibleRailSections(sections: CatalogRailSection[]): CatalogRailSection[] {
  return sections
    .map((section) => ({
      ...section,
      entries: section.entries.filter((entry) => entry.count > 0 || entry.active),
    }))
    .filter((section) => section.entries.length > 0);
}

const RailButton: React.FC<{
  row: CatalogRailRow;
  badge?: boolean;
  dotClassName?: string;
  section?: string;
  value?: string;
}> = ({ row, badge, dotClassName, section, value }) => (
  <button
    type="button"
    className={[styles.railButton, row.active ? styles.railButtonActive : ""]
      .filter(Boolean)
      .join(" ")}
    aria-pressed={row.active}
    onClick={row.onClick}
    data-curio-rail-section={section}
    data-curio-rail-value={value}
  >
    {dotClassName !== undefined ? (
      <span className={styles.railFormatItem}>
        <i className={`${styles.dot} ${dotClassName}`} data-curio-rail-dot="" />
        {row.label}
      </span>
    ) : (
      <span>{row.label}</span>
    )}
    <span className={badge ? styles.railCountBadge : styles.railCount}>{row.count}</span>
  </button>
);

export const CatalogRail: React.FC<CatalogRailProps> = ({ ariaLabel, all, scope, sections }) => (
  <aside className={styles.categoryRail} aria-label={ariaLabel}>
    <RailButton row={all} badge />
    {scope ? <RailButton row={scope} /> : null}
    {visibleRailSections(sections).map((section) => (
      <React.Fragment key={section.key}>
        <div className={styles.railDivider} aria-hidden="true" />
        <p className={styles.railLabel}>{section.label}</p>
        {section.entries.map((entry) => (
          <RailButton
            key={entry.value ?? entry.label}
            row={entry}
            dotClassName={entry.dotClassName}
            section={section.key}
            value={entry.value ?? entry.label}
          />
        ))}
      </React.Fragment>
    ))}
  </aside>
);

export default CatalogRail;
