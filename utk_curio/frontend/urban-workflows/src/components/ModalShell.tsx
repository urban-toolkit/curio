import React, { useEffect } from "react";
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

/** Mounted shells, innermost last: only the top one answers Escape. */
const openShells: symbol[] = [];

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

  // Escape closes the dialog, which is what role="dialog" aria-modal="true"
  // promises and what every other overlay in the app already does.
  //
  // Capture phase, and stopPropagation: the catalog drawers listen for Escape
  // on `window` in the bubble phase, so a modal opened from inside a drawer
  // used to let the key through and take the whole drawer down with it. A
  // capture listener on `document` runs first and stops the event there, so the
  // modal closes and the drawer behind it stays put.
  //
  // Same-node listeners are not stopped by stopPropagation, so stacking order
  // is tracked explicitly rather than left to registration order: with two
  // shells open, only the innermost responds.
  useEffect(() => {
    const id = Symbol("curio-modal");
    openShells.push(id);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (openShells[openShells.length - 1] !== id) return;
      event.stopPropagation();
      onClose();
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      const at = openShells.lastIndexOf(id);
      if (at !== -1) openShells.splice(at, 1);
    };
  }, [onClose]);
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
