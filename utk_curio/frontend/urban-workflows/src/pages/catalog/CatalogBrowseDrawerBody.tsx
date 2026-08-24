import React from "react";
import {
  CatalogDrawerTitle,
  type CatalogItemKind,
} from "../../components/catalog/CatalogKindVisuals";
import styles from "./CatalogBrowseLayout.module.css";

export interface CatalogDrawerInfoRow {
  label: string;
  value: React.ReactNode;
}

/** Rows may be conditionally absent (no CRS, no license…) — falsy entries drop out. */
export type CatalogDrawerInfoRows = Array<CatalogDrawerInfoRow | null | false | undefined>;

export interface CatalogBrowseDrawerBodyProps {
  kind: CatalogItemKind;
  /** Drawer chrome title, e.g. "Dataset details" / "Package details". */
  headerTitle: string;
  onClose: () => void;
  /** 112px hero block — a data preview, or the kind icon on its tinted panel. */
  hero: React.ReactNode;
  title: string;
  /** Badges row content; keep to `[format-or-category] [installed?]`. */
  badges: React.ReactNode;
  /** Publisher/provenance line under the title. */
  subtitle: React.ReactNode;
  metaLeft: React.ReactNode;
  metaRight: React.ReactNode;
  /** Drives the meta-row freshness dot (green within 24h, grey otherwise). */
  fresh: boolean;
  description?: string | null;
  infoLabel: string;
  infoRows: CatalogDrawerInfoRows;
  tags?: string[];
  /** Extra kind-specific sections, rendered after Tags. Use `CatalogDrawerSection`. */
  sections?: React.ReactNode;
  /** Full-width primary button (or a centred note when there is no action left). */
  primaryAction?: React.ReactNode;
  /** `CatalogPublishPill`, centred beneath the primary action. */
  publishPill?: React.ReactNode;
  /** Optional secondary button rendered under the primary action. */
  secondaryAction?: React.ReactNode;
}

/** A `drawerSection` with the standard uppercase label — for kind-specific blocks. */
export const CatalogDrawerSection: React.FC<{ label: string; children: React.ReactNode }> = ({
  label,
  children,
}) => (
  <div className={styles.drawerSection}>
    <p className={styles.drawerSectionLabel}>{label}</p>
    {children}
  </div>
);

/** Bulleted list styled from the stylesheet rather than inline styles. */
export const CatalogDrawerList: React.FC<{
  items: React.ReactNode[];
  moreLabel?: string | null;
}> = ({ items, moreLabel }) => (
  <ul className={styles.drawerList}>
    {items}
    {moreLabel ? <li className={styles.drawerListMore}>{moreLabel}</li> : null}
  </ul>
);

/**
 * The shared skeleton behind both catalog browse drawers.
 *
 * `/catalog` (packages) and `/data` (datasets) render the same screen and always
 * shared this stylesheet, but each page used to hand-assemble the markup, which is
 * how the two drifted apart — different badge semantics, different section-label
 * casing, inline styles on one side, and four different renderings of the word
 * "Published". Both drawers now feed this component instead, so a change to the
 * layout necessarily lands on both catalogs.
 */
export const CatalogBrowseDrawerBody: React.FC<CatalogBrowseDrawerBodyProps> = ({
  kind,
  headerTitle,
  onClose,
  hero,
  title,
  badges,
  subtitle,
  metaLeft,
  metaRight,
  fresh,
  description,
  infoLabel,
  infoRows,
  tags,
  sections,
  primaryAction,
  publishPill,
  secondaryAction,
}) => {
  const rows = infoRows.filter(Boolean) as CatalogDrawerInfoRow[];

  return (
    <>
      <div className={styles.drawerHeader}>
        <CatalogDrawerTitle kind={kind} title={headerTitle} />
        <button className={styles.drawerClose} type="button" aria-label="Close" onClick={onClose}>
          ✕
        </button>
      </div>

      {hero}

      <div className={styles.drawerDatasetName}>
        <h2>{title}</h2>
        <div className={styles.drawerBadgesRow}>{badges}</div>
      </div>

      <div className={styles.drawerPublisher}>
        <span className={styles.drawerPublisherText}>{subtitle}</span>
      </div>

      <div className={styles.drawerMeta}>
        <span>{metaLeft}</span>
        <span className={styles.drawerMetaRight}>
          <span className={`${styles.liveDot} ${fresh ? styles.liveDotGreen : styles.liveDotGray}`} />
          <span>{metaRight}</span>
        </span>
      </div>

      {description ? (
        <div className={styles.drawerSection}>
          <p className={styles.drawerDescription}>{description}</p>
        </div>
      ) : null}

      {rows.length > 0 ? (
        <CatalogDrawerSection label={infoLabel}>
          {rows.map((row) => (
            <div className={styles.infoRow} key={row.label}>
              <span className={styles.infoRowLabel}>{row.label}</span>
              <span className={styles.infoRowValue}>{row.value}</span>
            </div>
          ))}
        </CatalogDrawerSection>
      ) : null}

      {tags && tags.length > 0 ? (
        <CatalogDrawerSection label="Tags">
          <div className={styles.drawerTagsRow}>
            {tags.map((tag) => (
              <span key={tag} className={styles.drawerTag}>
                {tag}
              </span>
            ))}
          </div>
        </CatalogDrawerSection>
      ) : null}

      {sections}

      <div className={styles.drawerCtas}>
        {primaryAction}
        {secondaryAction}
        {publishPill ? <div className={styles.drawerPillRow}>{publishPill}</div> : null}
      </div>
    </>
  );
};
