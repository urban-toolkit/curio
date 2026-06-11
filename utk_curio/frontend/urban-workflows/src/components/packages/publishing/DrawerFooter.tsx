import React, { useRef } from "react";
import styles from "./DrawerFooter.module.css";

export interface DrawerFooterProps {
  busy: boolean;
  /** Called with the selected File when the user picks an archive/file. */
  onSideload: (file: File) => void;
  /** Accepted file types. Pass ``null`` to accept any file. Defaults to ``.curio.zip`` archives. */
  accept?: string | null;
  /** Button content. Defaults to the Node catalog's "Import package". */
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
        {label}
      </button>
    </footer>
  );
};
