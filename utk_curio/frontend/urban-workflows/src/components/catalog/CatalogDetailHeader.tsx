import React from "react";
import { CatalogKindIcon } from "./CatalogKindVisuals";
import type { CatalogItemKind } from "./CatalogKindVisuals";
import styles from "./CatalogDetailHeader.module.css";

export interface CatalogDetailHeaderProps {
  /** Picks the icon, and names it for assistive tech. */
  kind: CatalogItemKind;
  title: string;
  /** The publisher / version / license line under the title. */
  subtitle?: React.ReactNode;
  /** Right-hand controls, e.g. Export. */
  actions?: React.ReactNode;
  /** Extra content under the subtitle, e.g. the dataset meta row. */
  children?: React.ReactNode;
}

/**
 * The header every catalog's "View details" opens with.
 *
 * It exists because there were three of them. The Data panel built its own from
 * `DatasetDetailPanel.module.css`; the Agent and Node modals shared a second
 * one from `AgentDetailModal.module.css` and placed their action somewhere
 * else again. Same screen, three paddings, two title sizes, two places for the
 * action - and lining them up meant editing whichever stylesheet you happened
 * to be in, so they came apart again immediately.
 *
 * The `kind` prop is the only thing that varies between the three.
 */
export const CatalogDetailHeader: React.FC<CatalogDetailHeaderProps> = ({
  kind,
  title,
  subtitle,
  actions,
  children,
}) => (
  <div className={styles.header}>
    <div className={styles.titleBlock}>
      <CatalogKindIcon kind={kind} size="lg" title={title} />
      <div className={styles.titleText}>
        <h2 className={styles.title}>{title}</h2>
        {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
        {children}
      </div>
    </div>
    {actions ? <div className={styles.actions}>{actions}</div> : null}
  </div>
);

export default CatalogDetailHeader;
