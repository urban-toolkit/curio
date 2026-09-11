import React, { memo, useCallback, useEffect, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck, faCopy, faTriangleExclamation } from "@fortawesome/free-solid-svg-icons";
import styles from "./CopyButton.module.css";

/** How long the copied / failed state stays before reverting. */
const FEEDBACK_MS = 1800;

type CopyStatus = "idle" | "copied" | "failed";

export interface CopyButtonProps {
  /** The text handed to the clipboard. */
  value: string;
  /** What is being copied, for the accessible name: "Copy dataset reference". */
  label: string;
  /** `icon` — a bare square for a dense row; `labelled` — icon plus text. */
  variant?: "icon" | "labelled";
  className?: string;
}

/**
 * Copy a short string, and say whether it worked.
 *
 * Extracted from ``AgentCodeBlock``, which had the only implementation of this
 * in the codebase — the same idle/copied/failed cycle, the same 1800ms revert,
 * the same mounted guard. #206 needed it on four more surfaces, and a second
 * hand-rolled copy is how two of them end up behaving differently.
 *
 * Reports failure rather than swallowing it. ``navigator.clipboard`` rejects on
 * an insecure origin and when the document is not focused, and a button that
 * silently does nothing in those cases is worse than one that says so.
 */
export const CopyButton = memo(function CopyButton({
  value,
  label,
  variant = "icon",
  className,
}: CopyButtonProps) {
  const [status, setStatus] = useState<CopyStatus>("idle");
  const timerRef = useRef<number | undefined>(undefined);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      window.clearTimeout(timerRef.current);
    };
  }, []);

  const copy = useCallback(async () => {
    window.clearTimeout(timerRef.current);
    let next: CopyStatus;
    try {
      await navigator.clipboard.writeText(value);
      next = "copied";
    } catch (err) {
      console.warn(`Copying ${label} to clipboard failed`, err);
      next = "failed";
    }
    // The row can be unmounted by a refresh while the write is in flight.
    if (!mountedRef.current) return;
    setStatus(next);
    timerRef.current = window.setTimeout(() => {
      if (mountedRef.current) setStatus("idle");
    }, FEEDBACK_MS);
  }, [value, label]);

  const name = status === "copied" ? "Copied" : status === "failed" ? `${label} failed` : label;
  const icon =
    status === "copied" ? faCheck : status === "failed" ? faTriangleExclamation : faCopy;

  return (
    <button
      type="button"
      className={`${styles.root} ${styles[variant]} ${className ?? ""}`}
      // Both, deliberately: the title is what a mouse user gets and the
      // aria-label is what a screen reader gets, and an icon-only button has no
      // other name.
      title={name}
      aria-label={name}
      data-copy-status={status}
      onClick={(event) => {
        // These sit inside rows that are themselves clickable (a palette row
        // selects nodes on the canvas; a card opens its details).
        event.preventDefault();
        event.stopPropagation();
        void copy();
      }}
    >
      <FontAwesomeIcon icon={icon} aria-hidden />
      {variant === "labelled" ? <span className={styles.text}>{name}</span> : null}
    </button>
  );
});

export default CopyButton;
