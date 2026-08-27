import React from "react";
import { createPortal } from "react-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faXmark } from "@fortawesome/free-solid-svg-icons";
import styles from "./ModalShell.module.css";

interface ModalShellProps {
  onClose: () => void;
  children: React.ReactNode;
  size?: "default" | "large" | "xlarge";
  /** Stack above canvas dock / catalog overlays (--curio-z-modal). */
  layer?: "default" | "overlay";
  /** Keep the packages palette dock open while this modal is interacted with. */
  preservePackagePaletteOpen?: boolean;
  /** id of the consumer's heading, wired to aria-labelledby - the same contract
   *  as DrawerHeader's titleId. Prefer this when the modal renders a heading. */
  titleId?: string;
  /** Accessible name for consumers with no usable heading (GenericDialog's
   *  children are arbitrary; TrillProvenanceWindow titles with a <p>). Ignored
   *  when titleId is given. */
  label?: string;
}

export default function ModalShell({
  onClose,
  children,
  size = "default",
  layer = "default",
  preservePackagePaletteOpen = false,
  titleId,
  label,
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
      {/* role="dialog" on the shell, so every modal is announced as one and is
          reachable by the same role queries the catalog drawers already answer.
          The drawers had this from the start; the modals never did, which left
          a screen reader with an unlabeled group and tests with nothing to
          target but headings. */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-label={titleId ? undefined : label}
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
