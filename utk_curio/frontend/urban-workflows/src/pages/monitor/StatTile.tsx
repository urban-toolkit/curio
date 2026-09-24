import React from "react";
import styles from "./StatTile.module.css";

/**
 * One headline number with a label and a line of context.
 *
 * A handful of related numbers is a KPI row, not a grouped bar chart: the
 * comparison people actually make is "is this bigger than I expected", which a
 * large numeral answers and a chart obscures.
 */
export interface StatTileProps {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  hero?: boolean;
  tone?: "neutral" | "warn" | "danger";
}

export const StatTile: React.FC<StatTileProps> = ({
  label,
  value,
  sub,
  hero = false,
  tone = "neutral",
}) => (
  <div
    className={[
      styles.tile,
      hero ? styles.hero : "",
      tone !== "neutral" ? styles[tone] : "",
    ]
      .filter(Boolean)
      .join(" ")}
  >
    <div className={styles.label}>{label}</div>
    <div className={styles.value}>{value}</div>
    {sub ? <div className={styles.sub}>{sub}</div> : null}
  </div>
);

/**
 * A single ratio against a limit.
 *
 * One value measured against a maximum is a meter, never a two-slice pie: the
 * question is "how full", and a filled track answers it at a glance without
 * spending a second colour on the remainder.
 */
export interface MeterProps {
  label: string;
  value: number;
  max: number;
  caption?: React.ReactNode;
  tone?: "neutral" | "warn" | "danger";
}

export const Meter: React.FC<MeterProps> = ({
  label,
  value,
  max,
  caption,
  tone = "neutral",
}) => {
  const safeMax = max > 0 ? max : 1;
  const pct = Math.max(0, Math.min(100, (value / safeMax) * 100));
  return (
    <div className={styles.meterBlock}>
      <div className={styles.meterHead}>
        <span className={styles.label}>{label}</span>
        <span className={styles.meterCaption}>{caption}</span>
      </div>
      <div
        className={styles.meterTrack}
        role="meter"
        aria-label={label}
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={safeMax}
      >
        <div
          className={[styles.meterFill, tone !== "neutral" ? styles[tone] : ""]
            .filter(Boolean)
            .join(" ")}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
};

/** A labelled state, for configuration facts that are not quantities. */
export const Chip: React.FC<{
  label: string;
  value: React.ReactNode;
  tone?: "neutral" | "good" | "warn" | "danger";
}> = ({ label, value, tone = "neutral" }) => (
  <div className={styles.chipRow}>
    <span className={styles.chipLabel}>{label}</span>
    {/* The tone is never the only signal: every chip carries its text too, so
        it reads the same to someone who cannot separate the colours. */}
    <span className={[styles.chip, styles[`chip_${tone}`]].join(" ")}>{value}</span>
  </div>
);

export default StatTile;
