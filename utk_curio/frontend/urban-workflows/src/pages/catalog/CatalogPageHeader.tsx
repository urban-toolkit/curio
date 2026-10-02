/**
 * The header band of every browse page, in two rows:
 * - the page's icon, title and count, then its tools (search, import);
 * - the intro, then the controls for how the cards are shown (sort, and on
 *   Projects the grid or list switch), right above the cards they arrange.
 *
 * It used to be four rows: a crumb repeating the active tab and the title, the
 * title, the intro, then the tools; and a chip row under it repeating the rail.
 * Together they pushed the first card below the middle of a 720px window.
 */
import React from "react";

import {
  CatalogKindIcon,
  type CatalogItemKind,
} from "../../components/catalog/CatalogKindVisuals";
import styles from "./CatalogBrowseLayout.module.css";

export interface CatalogPageHeaderProps {
  kind: CatalogItemKind;
  /** The icon's accessible title. */
  iconTitle: string;
  title: string;
  count: number;
  intro: React.ReactNode;
  /** Sort, and any other control over how the cards are laid out. */
  viewTools?: React.ReactNode;
  /** Search and the page's actions, at the end of the title row. */
  children?: React.ReactNode;
}

export const CatalogPageHeader: React.FC<CatalogPageHeaderProps> = ({
  kind,
  iconTitle,
  title,
  count,
  intro,
  viewTools,
  children,
}) => (
  <section className={styles.browseHeader}>
    <div className={styles.titleRow}>
      <CatalogKindIcon kind={kind} size="md" title={iconTitle} />
      <h1>{title}</h1>
      <span className={styles.titleCount}>{count}</span>
      <div className={styles.headerTools}>{children}</div>
    </div>
    <div className={styles.introRow}>
      <p className={styles.pageIntro}>{intro}</p>
      {viewTools ? <div className={styles.viewTools}>{viewTools}</div> : null}
    </div>
  </section>
);

export default CatalogPageHeader;
