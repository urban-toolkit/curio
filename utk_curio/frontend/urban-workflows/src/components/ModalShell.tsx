import React from "react";
import { createPortal } from "react-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faXmark } from "@fortawesome/free-solid-svg-icons";
import styles from "./ModalShell.module.css";

interface ModalShellProps {
  onClose: () => void;
  children: React.ReactNode;
  size?: "default" | "large";
  /** Stack above canvas dock / warehouse overlays (z-index ~10055). */
  layer?: "default" | "overlay";
  /** Keep the packs palette dock open while this modal is interacted with. */
  preservePackPaletteOpen?: boolean;
}

export default function ModalShell({
  onClose,
  children,
  size = "default",
  layer = "default",
  preservePackPaletteOpen = false,
}: ModalShellProps) {
  const packPaletteActionAttr = preservePackPaletteOpen
    ? ({ "data-curio-pack-palette-node-action": "true" } as const)
    : {};
  const shell = (
    <>
      <div
        className={`${styles.backdrop} nowheel nodrag nopan${
          layer === "overlay" ? ` ${styles.backdropOverlay}` : ""
        }`}
        onClick={onClose}
        {...packPaletteActionAttr}
      />
      <div
        className={`${styles.modal} nowheel nodrag nopan${
          size === "large" ? ` ${styles.large}` : ""
        }${layer === "overlay" ? ` ${styles.modalOverlay}` : ""}`}
        {...packPaletteActionAttr}
      >
        <button className={styles.closeX} onClick={onClose} aria-label="Close">
          <FontAwesomeIcon icon={faXmark} />
        </button>
        {children}
      </div>
    </>
  );

  if (typeof document === "undefined") return shell;
  return createPortal(shell, document.body);
}
