import React, { useRef } from "react";
import { Link } from "react-router-dom";
import styles from "./HubTopBar.module.css";

export interface HubTopBarProps {
  busy: boolean;
  /** Called with the selected File when the user picks a sideload archive. */
  onSideload: (file: File) => void;
  /** Called when the user clicks "Create new pack". */
  onCreateNew: () => void;
}

/**
 * Top navigation bar for the Nodes Hub page.
 * Contains the back link, page title, sideload file picker, and create-new-pack CTA.
 */
export const HubTopBar: React.FC<HubTopBarProps> = ({ busy, onSideload, onCreateNew }) => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <div className={styles.topBar}>
      <Link to="/projects" className={styles.backLink}>
        ← Projects
      </Link>

      <h1 className={styles.title}>Nodes warehouse</h1>

      <input
        ref={fileInputRef}
        type="file"
        accept=".curio-nodepack,application/zip"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onSideload(file);
          if (fileInputRef.current) fileInputRef.current.value = "";
        }}
      />

      <button
        type="button"
        className={styles.ghostButton}
        disabled={busy}
        onClick={() => fileInputRef.current?.click()}
      >
        Sideload .curio-nodepack
      </button>

      <button
        type="button"
        className={styles.actionButton}
        onClick={onCreateNew}
      >
        Create new pack
      </button>
    </div>
  );
};

