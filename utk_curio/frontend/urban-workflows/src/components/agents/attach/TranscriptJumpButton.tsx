import React, { useEffect, useRef } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown } from "@fortawesome/free-solid-svg-icons";
import styles from "./TranscriptJumpButton.module.css";

/**
 * Compact "Jump to latest" pill for chat transcripts (memo dev/75).
 *
 * Shown only while the user has scrolled away from the bottom (newer content
 * below the viewport). Renders as an absolute overlay centered above the
 * transcript's bottom edge — the parent supplies the positioning context
 * (a `position: relative` wrapper around the scroll container).
 */
export const TranscriptJumpButton: React.FC<{
  visible: boolean;
  /** Scroll to the newest message and resume auto-follow. */
  onJump: () => void;
  /** Messages landed since the user scrolled away (dev/83): ≥1 renders
   * "N new" (display capped at 99+) instead of "Latest"; the accessible name
   * carries the real number. Absent/0 → the dev/75 pill, unchanged. */
  count?: number;
  /** Receives focus if the pill disappears while focused, so keyboard focus
   * is never stranded on a removed element. */
  focusFallbackRef?: React.RefObject<HTMLElement | null>;
}> = ({ visible, onJump, count, focusFallbackRef }) =>
  visible ? <JumpPill onJump={onJump} count={count} focusFallbackRef={focusFallbackRef} /> : null;

const JumpPill: React.FC<{
  onJump: () => void;
  count?: number;
  focusFallbackRef?: React.RefObject<HTMLElement | null>;
}> = ({ onJump, count, focusFallbackRef }) => {
  const hadFocus = useRef(false);

  useEffect(() => {
    return () => {
      if (hadFocus.current) focusFallbackRef?.current?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const n = count ?? 0;
  const label = n >= 1 ? `${n > 99 ? "99+" : n} new` : "Latest";
  const ariaLabel =
    n >= 1
      ? `Jump to ${n} new message${n === 1 ? "" : "s"}`
      : "Jump to latest messages";

  return (
    <button
      type="button"
      className={styles.jump}
      aria-label={ariaLabel}
      onClick={onJump}
      onFocus={() => (hadFocus.current = true)}
      onBlur={() => (hadFocus.current = false)}
    >
      <FontAwesomeIcon icon={faChevronDown} aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
};
