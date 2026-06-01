import React from "react";
import { createPortal } from "react-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faXmark } from "@fortawesome/free-solid-svg-icons";
import styles from "./ModalShell.module.css";

interface ModalShellProps {
  onClose: () => void;
  children: React.ReactNode;
  size?: "default" | "large" | "xlarge";
  /** Stack above canvas dock / catalog overlays (z-index ~10055). */
  layer?: "default" | "overlay";
  /** Keep the packages palette dock open while this modal is interacted with. */
  preservePackagePaletteOpen?: boolean;
}

export default function ModalShell({
  onClose,
  children,
  size = "default",
  layer = "default",
  preservePackagePaletteOpen = false,
}: ModalShellProps) {
  const packagePaletteActionAttr = preservePackagePaletteOpen
    ? ({ "data-curio-package-palette-node-action": "true" } as const)
    : {};
  const shell = (
    <>
      <div
        className={`${styles.backdrop} nowheel nodrag nopan${
          layer === "overlay" ? ` ${styles.backdropOverlay}` : ""
        }`}
        onClick={onClose}
        {...packagePaletteActionAttr}
      />
      <div
        className={`${styles.modal} nowheel nodrag nopan${
          size === "large" ? ` ${styles.large}` : ""
        }${size === "xlarge" ? ` ${styles.xlarge}` : ""}${
          layer === "overlay" ? ` ${styles.modalOverlay}` : ""
        }${size === "xlarge" && layer === "overlay" ? ` ${styles.xlargeOverlay}` : ""}`}
        {...packagePaletteActionAttr}
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
