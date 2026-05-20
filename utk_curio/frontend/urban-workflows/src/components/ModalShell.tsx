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
}

export default function ModalShell({
  onClose,
  children,
  size = "default",
  layer = "default",
}: ModalShellProps) {
  const shell = (
    <>
      <div
        className={`${styles.backdrop} nowheel nodrag nopan${
          layer === "overlay" ? ` ${styles.backdropOverlay}` : ""
        }`}
        onClick={onClose}
      />
      <div
        className={`${styles.modal} nowheel nodrag nopan${
          size === "large" ? ` ${styles.large}` : ""
        }${layer === "overlay" ? ` ${styles.modalOverlay}` : ""}`}
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
