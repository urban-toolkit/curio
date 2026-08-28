import React, { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faXmark } from "@fortawesome/free-solid-svg-icons";
import styles from "./ModalShell.module.css";

/** Every mounted ModalShell.
 *
 * Escape must reach exactly one overlay, and two things make that awkward. The
 * catalog drawers listen on `window` too, and a drawer that renders a modal
 * inside itself (the Agent Catalog holds AI Settings and agent import) mounted
 * first — so its listener runs first and `stopPropagation` from the modal cannot
 * help. `modalStackDepth` lets those drawers stand down instead.
 *
 * Among modals, "which one is on top" is decided from the DOM rather than from
 * mount order: React commits child effects before parent ones, so the registry
 * order is inside-out and cannot be trusted for it.
 */
const modalStack = new Set<symbol>();

/** How many ModalShell dialogs are currently open. */
export function modalStackDepth(): number {
  return modalStack.size;
}

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
  // Escape closes the dialog. Deliberately routed through the same `onClose`
  // the backdrop and the X use, so a consumer that passes `busy ? () => {} :
  // onClose` (NodeSaveAsModal, PackageMetadataModal) keeps Escape inert
  // mid-save without knowing this exists.
  //
  // Read through a ref so the listener is registered once per mount rather than
  // re-registered whenever the parent re-renders with a fresh closure.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const token = Symbol("curio-modal");
    modalStack.add(token);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const self = dialogRef.current;
      if (!self) return;
      // Only the dialog on top responds, so a modal opened over another does
      // not close both. Portals all land in document.body, so the last matching
      // node in document order is the one painted on top.
      const open = document.querySelectorAll<HTMLElement>(
        '[data-curio-modal-shell="true"]',
      );
      if (open.length > 1 && open[open.length - 1] !== self) return;
      event.stopPropagation();
      onCloseRef.current();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      modalStack.delete(token);
    };
  }, []);

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
        ref={dialogRef}
        data-curio-modal-shell="true"
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
