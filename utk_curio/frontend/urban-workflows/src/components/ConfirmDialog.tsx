import React, { useId } from "react";
import ModalShell from "./ModalShell";
import styles from "./ConfirmDialog.module.css";

export interface ConfirmDialogProps {
  title: string;
  /** Paragraph text, or arbitrary content when a call site needs a list.
   *
   *  A plain string is split on blank lines into paragraphs, so the copy the
   *  native `window.confirm` calls already carried (with its `\n\n` breaks)
   *  moves across verbatim — which is what keeps the #177 usage wording and
   *  the tests that assert it intact. */
  body?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Paints the confirm button as a destructive action and moves the initial
   *  focus to Cancel, so a stray Enter cannot delete anything. */
  destructive?: boolean;
  /**
   * Paint override for a confirmation that is cautious but not destructive.
   *
   * `destructive` bundled two things: the red confirm button AND moving initial
   * focus to Cancel. Unpublish wants the second and not the first - it removes
   * a listing, it destroys nothing, and it is undone by publishing again - but
   * red is also outside the catalogs' two-colour vocabulary (dark = action,
   * light = destructive), where it read as a third, louder category.
   */
  tone?: "danger" | "plain";
  busy?: boolean;
  /** ``"overlay"`` stacks the dialog above a catalog drawer.
   *
   *  The drawers sit at ``--curio-z-agent-drawer`` / ``--curio-z-node-drawer``
   *  (~10050), well above ModalShell's default ``--curio-z-modal-base`` (500).
   *  A confirmation opened FROM a drawer therefore rendered underneath it: the
   *  dialog is centred on the viewport, the drawer covers the right of the
   *  screen, and the confirm button - the rightmost thing in the footer - was
   *  painted over and could not be clicked at all. Any call site inside a
   *  drawer must pass this. */
  layer?: "default" | "overlay";
  onConfirm: () => void;
  onCancel: () => void;
}

/** The app's replacement for `window.confirm` (#197).
 *
 * Built on `ModalShell` so it inherits the portal, the backdrop click, the
 * topmost-only Escape handling and the `modalStackDepth()` registration that
 * the catalog drawers' own Escape listeners stand down for.
 *
 * Deliberately *not* routed through `DialogProvider`: that provider is mounted
 * only inside `MainCanvasRoute`, so it cannot serve `/catalog/*` or
 * `/projects`, and `GenericDialog` hardcodes `label="Dialog"` as the
 * accessible name. Call sites hold their own "what am I confirming" state
 * instead, which is also what lets them keep the pending item around for the
 * confirm callback.
 */
export default function ConfirmDialog({
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  tone,
  busy = false,
  layer = "default",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();

  const renderedBody =
    typeof body === "string"
      ? body
          .split(/\n{2,}/)
          .map((para) => para.trim())
          .filter(Boolean)
          .map((para, i) => (
            <p key={i} className={styles.bodyText}>
              {para}
            </p>
          ))
      : body;

  return (
    // Escape and the backdrop both mean "cancel". Held inert while busy so a
    // confirm that kicked off a slow uninstall cannot be dismissed mid-flight.
    <ModalShell onClose={busy ? () => {} : onCancel} titleId={titleId} layer={layer}>
      <div className={styles.dialog}>
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        {renderedBody != null && <div className={styles.body}>{renderedBody}</div>}
        <div className={styles.footer}>
          <button
            type="button"
            className={styles.ghostButton}
            onClick={onCancel}
            disabled={busy}
            autoFocus={destructive}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`${styles.actionButton}${
              (tone ?? (destructive ? "danger" : "plain")) === "danger"
                ? ` ${styles.destructive}`
                : ""
            }`}
            onClick={onConfirm}
            disabled={busy}
            autoFocus={!destructive}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}
