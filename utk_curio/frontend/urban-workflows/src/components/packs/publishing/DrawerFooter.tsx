import React, { useRef } from "react";
import styles from "./DrawerFooter.module.css";

export interface DrawerFooterProps {
  busy: boolean;
  /** Called with the selected File when the user picks a sideload archive. */
  onSideload: (file: File) => void;
  /** Called when the user clicks "Open full warehouse". */
  onOpenWarehouse: () => void;
}

/**
 * Sticky footer rendered at the bottom of the Node Warehouse drawer.
 * Provides a hidden file input for sideloading .curio-nodepack archives
 * and a primary CTA to open the full warehouse page.
 */
export const DrawerFooter: React.FC<DrawerFooterProps> = ({ busy, onSideload, onOpenWarehouse }) => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <footer className={styles.footer}>
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
        className={styles.footerGhost}
        disabled={busy}
        onClick={() => fileInputRef.current?.click()}
      >
        Sideload .curio-nodepack
      </button>
      <button
        type="button"
        className={styles.footerPrimary}
        onClick={onOpenWarehouse}
      >
        Open full warehouse
      </button>
    </footer>
  );
};

