import React, { useRef } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faFileImport } from "@fortawesome/free-solid-svg-icons";
import styles from "./DrawerFooter.module.css";

export interface DrawerFooterProps {
  busy: boolean;
  /** Called with the selected File when the user picks an archive/file. */
  onSideload: (file: File) => void;
  /** Accepted file types. Pass ``null`` to accept any file. Defaults to ``.curio.zip`` archives. */
  accept?: string | null;
  /**
   * What the button says while an import is in flight. Sideloading now installs
   * the archive's declared python deps, so this click can sit in pip for
   * minutes where it used to return in under a second - and a button that
   * still reads "Import package" while disabled looks broken rather than busy.
   */
  busyLabel?: React.ReactNode;
  /** Button content. Defaults to the Node Catalog's "Import package". */
  label?: React.ReactNode;
}

/**
 * Sticky footer shared by the Node Catalog and Data Catalog drawers.
 * Provides a hidden file input for importing archives/datasets.
 */
export const DrawerFooter: React.FC<DrawerFooterProps> = ({
  busy,
  onSideload,
  accept = ".curio.zip,.zip,application/zip",
  label = "Import package",
  busyLabel = "Importing…",
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <footer className={styles.footer}>
      <input
        ref={fileInputRef}
        type="file"
        {...(accept != null ? { accept } : {})}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onSideload(file);
          if (fileInputRef.current) fileInputRef.current.value = "";
        }}
      />
      <button
        type="button"
        className={styles.footerPrimary}
        disabled={busy}
        onClick={() => fileInputRef.current?.click()}
      >
        {/* One icon, rendered here rather than passed in, so every drawer's
            import wears the same glyph. The Data drawer used to pass its own
            and the Node drawer passed none, so two footers built from this very
            component still looked different. The Agent drawer has its own
            footer element and imports the same icon. */}
        <FontAwesomeIcon icon={faFileImport} aria-hidden />{" "}
        {busy ? busyLabel : label}
      </button>
    </footer>
  );
};
