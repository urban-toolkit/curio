import React from "react";
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCube, faDatabase } from "@fortawesome/free-solid-svg-icons";
import styles from "./CatalogKindVisuals.module.css";

export type CatalogItemKind = "dataset" | "package";

export interface CatalogKindMeta {
  icon: IconDefinition;
  label: string;
  shortLabel: string;
}

export const CATALOG_KIND_META: Record<CatalogItemKind, CatalogKindMeta> = {
  dataset: {
    icon: faDatabase,
    label: "Dataset",
    shortLabel: "Data",
  },
  package: {
    icon: faCube,
    label: "Package",
    shortLabel: "Package",
  },
};

export type CatalogKindIconSize = "sm" | "md" | "lg";

export interface CatalogKindIconProps {
  kind: CatalogItemKind;
  size?: CatalogKindIconSize;
  className?: string;
  title?: string;
  children?: React.ReactNode;
}

export const CatalogKindIcon: React.FC<CatalogKindIconProps> = ({
  kind,
  size = "md",
  className,
  title,
  children,
}) => {
  const meta = CATALOG_KIND_META[kind];
  return (
    <span
      className={[
        styles.kindIcon,
        styles[`kindIcon_${kind}`],
        styles[`size_${size}`],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      title={title ?? meta.label}
      aria-hidden={title ? undefined : true}
    >
      {children}
      <FontAwesomeIcon icon={meta.icon} />
    </span>
  );
};

export interface CatalogItemStripHeaderProps {
  kind: CatalogItemKind;
  badge?: React.ReactNode;
  trailing?: React.ReactNode;
}

/** Top strip content for catalog browse cards — type icon + kind label + optional badge. */
export const CatalogItemStripHeader: React.FC<CatalogItemStripHeaderProps> = ({
  kind,
  badge,
  trailing,
}) => {
  const meta = CATALOG_KIND_META[kind];
  return (
    <div className={styles.stripRoot}>
      <div className={styles.stripLeading}>
        <span className={styles.stripTypeIcon} title={meta.label} aria-hidden>
          <FontAwesomeIcon icon={meta.icon} />
        </span>
        <span className={styles.stripKindLabel}>{meta.label}</span>
        {badge ? (
          <>
            <span className={styles.stripDivider} aria-hidden />
            <span className={styles.stripBadgeSlot}>{badge}</span>
          </>
        ) : null}
      </div>
      {trailing ? <div className={styles.stripTrailing}>{trailing}</div> : null}
    </div>
  );
};

export interface CatalogDrawerTitleProps {
  kind: CatalogItemKind;
  title: string;
}

export const CatalogDrawerTitle: React.FC<CatalogDrawerTitleProps> = ({ kind, title }) => (
  <div className={styles.titleWithKind}>
    <CatalogKindIcon kind={kind} size="sm" title={CATALOG_KIND_META[kind].label} />
    <p className={styles.drawerTitleText}>{title}</p>
  </div>
);

export interface CatalogFormatBadgeProps {
  label: string;
  formatKey: string;
}

export const CatalogFormatBadge: React.FC<CatalogFormatBadgeProps> = ({ label, formatKey }) => (
  <span
    className={[styles.formatBadge, styles[`formatBadge_${formatKey}`]].filter(Boolean).join(" ")}
  >
    {label}
  </span>
);

export interface CatalogCategoryBadgeProps {
  label: string;
}

export const CatalogCategoryBadge: React.FC<CatalogCategoryBadgeProps> = ({ label }) => (
  <span className={styles.categoryBadge}>{label}</span>
);

export interface CatalogItemRowHeaderProps {
  kind: CatalogItemKind;
  badge?: React.ReactNode;
  onClick?: () => void;
  buttonLabel?: string;
}

/** Inline header for list-style catalog items — mirrors palette row icon + badge. */
export const CatalogItemRowHeader: React.FC<CatalogItemRowHeaderProps> = ({
  kind,
  badge,
  onClick,
  buttonLabel,
}) => {
  const content = (
    <>
      <CatalogKindIcon kind={kind} size="sm" title={CATALOG_KIND_META[kind].label} />
      {badge}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className={`${styles.rowHeader} ${styles.rowHeaderButton}`}
        onClick={onClick}
        aria-label={buttonLabel ?? CATALOG_KIND_META[kind].label}
      >
        {content}
      </button>
    );
  }

  return <div className={styles.rowHeader}>{content}</div>;
};
