import React, { useRef } from "react";
import styles from "./DrawerFooter.module.css";

export interface DrawerFooterProps {
  busy: boolean;
  /** Called with the selected File when the user picks a sideload archive. */
  onSideload: (file: File) => void;
  /** Opens the Node Factory wizard modal so the user can author a new package. */
  onCreatePack: () => void;
}

/**
 * Sticky footer rendered at the bottom of the Node Warehouse drawer.
 * Provides a hidden file input for sideloading ``.curio-package`` archives
 * and a primary CTA that opens the Node Factory wizard modal for authoring
 * a new package from scratch.
 */
export const DrawerFooter: React.FC<DrawerFooterProps> = ({ busy, onSideload, onCreatePack }) => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <footer className={styles.footer}>
      <input
        ref={fileInputRef}
        type="file"
        accept=".curio-package,application/zip"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onSideload(file);
          if (fileInputRef.current) fileInputRef.current.value = "";
        }}
      />
      <button
        type="button"
        className={styles.footerGhost}
        disabled={busy}
        onClick={() => fileInputRef.current?.click()}
      >
        Sideload .curio-package
      </button>
      <button
        type="button"
        className={styles.footerPrimary}
        disabled={busy}
        onClick={onCreatePack}
      >
        Create new package
      </button>
    </footer>
  );
};

