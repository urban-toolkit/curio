import React from "react";
import styles from "./EnvNote.module.css";

/**
 * Static informational banner that explains the shared Python sandbox
 * environment used for package dependency installation.
 */
export const EnvNote: React.FC = () => (
  <div className={styles.envNote}>
    <span className={styles.envIcon} aria-hidden>
      i
    </span>
    <div>
      <p className={styles.envTitle}>Shared Python environment</p>
      <p className={styles.envText}>
        Package Python deps install into the interpreter Curio itself runs on,
        which every dataflow and every user of this instance shares - not into
        this project alone. Conflicting versions fail at install, and removing a
        package uninstalls them again for everyone.
      </p>
    </div>
  </div>
);

