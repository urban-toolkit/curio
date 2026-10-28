import React from "react";
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faBookOpen,
  faBrain,
  faCloudArrowDown,
  faCube,
  faDatabase,
  faDiagramProject,
  faObjectGroup,
  faRobot,
} from "@fortawesome/free-solid-svg-icons";
import styles from "./CatalogKindVisuals.module.css";

export type CatalogItemKind =
  | "dataset"
  | "package"
  | "dataflow"
  | "agent"
  | "skill"
  | "source"
  | "model"
  | "scenario";

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
  dataflow: {
    icon: faDiagramProject,
    label: "Dataflow",
    shortLabel: "Flow",
  },
  agent: {
    icon: faRobot,
    label: "Agent",
    shortLabel: "Agent",
  },
  // An Agent Catalog SKILL: what tells an agent how to do a specific task. The
  // open book is the instructions it holds, beside the agent that reads them.
  skill: {
    icon: faBookOpen,
    label: "Skill",
    shortLabel: "Skill",
  },
  // A Discovery Catalog SOURCE: a portal you pull from. The download arrow says what
  // you do with one, which is more use than a drop of water would be - and it
  // is what distinguishes a source card from the dataset card it produces.
  source: {
    icon: faCloudArrowDown,
    label: "Source",
    shortLabel: "Source",
  },
  // A Model Catalog MODEL: trained weights a node runs. The brain is the
  // common mark for a learned model, and nothing else in the catalogs uses it.
  model: {
    icon: faBrain,
    label: "Model",
    shortLabel: "Model",
  },
  // A Scenario Catalog SCENARIO: a named selection of a project's nodes. The
  // glyph is the one View > "Save selection as scenario" shows.
  scenario: {
    icon: faObjectGroup,
    label: "Scenario",
    shortLabel: "Scenario",
  },
};

export type CatalogKindIconSize = "sm" | "md" | "lg";

export interface CatalogKindIconProps {
  kind: CatalogItemKind;
  size?: CatalogKindIconSize;
  className?: string;
  /** Its tooltip, and its name for assistive tech unless it is *decorative*. */
  title?: string;
  /** The same words are written beside it, so it is hidden from assistive tech. */
  decorative?: boolean;
  children?: React.ReactNode;
}

export const CatalogKindIcon: React.FC<CatalogKindIconProps> = ({
  kind,
  size = "md",
  className,
  title,
  decorative = false,
  children,
}) => {
  const named = !!title && !decorative;
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
      data-tooltip={title ?? meta.label}
      // Given a title, the icon names what it shows, in the tooltip's words;
      // else it only decorates the words beside it.
      role={named ? "img" : undefined}
      aria-label={named ? title : undefined}
      aria-hidden={named ? undefined : true}
    >
      {children}
      <FontAwesomeIcon icon={meta.icon} />
    </span>
  );
};

export interface CatalogItemStripHeaderProps {
  kind: CatalogItemKind;
  badge?: React.ReactNode;
}

/**
 * Top strip content for catalog browse cards: type icon + kind label + optional badge.
 *
 * Identity only. A card's state ("In all projects", "Link only") sits at the
 * start of its actions row: on a card a grid column wide it ran over the badge
 * when it shared this strip.
 */
export const CatalogItemStripHeader: React.FC<CatalogItemStripHeaderProps> = ({
  kind,
  badge,
}) => {
  const meta = CATALOG_KIND_META[kind];
  return (
    <div className={styles.stripRoot}>
      <div className={styles.stripLeading}>
        <span className={styles.stripTypeIcon} data-tooltip={meta.label} aria-hidden>
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
