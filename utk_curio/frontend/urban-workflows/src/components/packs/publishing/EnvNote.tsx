import React from "react";
import styles from "./EnvNote.module.css";

/**
 * Static informational banner that explains the shared Python sandbox
 * environment used for pack dependency installation.
 */
export const EnvNote: React.FC = () => (
  <div className={styles.envNote}>
    <span className={styles.envIcon} aria-hidden>
      i
    </span>
    <div>
      <p className={styles.envTitle}>Shared project environment</p>
      <p className={styles.envText}>
        Pack python deps install into this project&apos;s sandbox interpreter;
        conflicting versions fail at install.
      </p>
    </div>
  </div>
);

