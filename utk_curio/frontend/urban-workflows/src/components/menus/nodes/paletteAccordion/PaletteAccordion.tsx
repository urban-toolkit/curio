import React, { memo } from "react";
import styles from "./PaletteAccordion.module.css";

export interface PaletteAccordionProps {
  title: string;
  titleTooltip?: string;
  count?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  defaultOpen?: boolean;
  selected?: boolean;
  onSummaryClick?: React.MouseEventHandler<HTMLElement>;
}

export const PaletteAccordion = memo(function PaletteAccordion({
  title,
  titleTooltip,
  count,
  actions,
  children,
  className,
  bodyClassName,
  defaultOpen,
  selected,
  onSummaryClick,
}: PaletteAccordionProps) {
  return (
    <details
      className={`${styles.details} ${selected ? styles.detailsSelected : ""} ${className || ""}`}
      open={defaultOpen || undefined}
    >
      <summary className={styles.summary} onClick={onSummaryClick}>
        <div className={styles.summaryRow}>
          <div className={styles.summaryTitleCluster}>
            <span className={styles.summaryTitle} title={titleTooltip || title}>{title}</span>
            {actions}
          </div>
          {count != null ? <span className={styles.summaryCount}>{count}</span> : null}
        </div>
      </summary>
      <div className={`${styles.body} ${bodyClassName || ""}`}>{children}</div>
    </details>
  );
});
