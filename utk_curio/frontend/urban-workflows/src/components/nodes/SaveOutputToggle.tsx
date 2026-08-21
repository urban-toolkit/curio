import React, { memo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDatabase } from "@fortawesome/free-solid-svg-icons";
import styles from "./SaveOutputToggle.module.css";

export interface SaveOutputToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** `node` — compact control beside the per-node play button; `toolbar` — Play-all rail. */
  variant?: "node" | "toolbar";
  id?: string;
}

export const SaveOutputToggle = memo(function SaveOutputToggle({
  checked,
  onChange,
  disabled = false,
  variant = "node",
  id,
}: SaveOutputToggleProps) {
  const inputId = id ?? `save-output-${variant}`;

  return (
    <label
      className={`${styles.root} ${styles[variant]} ${checked ? styles.rootOn : ""} ${disabled ? styles.rootDisabled : ""}`}
      title={checked ? "Save tabular output to Data Catalog on run" : "Run without saving to Data Catalog"}
      aria-label={checked ? "Save output to Data Catalog enabled" : "Save output to Data Catalog disabled"}
    >
      <input
        id={inputId}
        type="checkbox"
        className={styles.input}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <FontAwesomeIcon icon={faDatabase} className={styles.icon} aria-hidden />
      <span className={styles.track} aria-hidden>
        <span className={styles.thumb} />
      </span>
      {variant === "toolbar" ? <span className={styles.label}>Save</span> : null}
    </label>
  );
});
