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
  /** Receives focus if the pill disappears while focused, so keyboard focus
   * is never stranded on a removed element. */
  focusFallbackRef?: React.RefObject<HTMLElement | null>;
}> = ({ visible, onJump, focusFallbackRef }) =>
  visible ? <JumpPill onJump={onJump} focusFallbackRef={focusFallbackRef} /> : null;

const JumpPill: React.FC<{
  onJump: () => void;
  focusFallbackRef?: React.RefObject<HTMLElement | null>;
}> = ({ onJump, focusFallbackRef }) => {
  const hadFocus = useRef(false);

  useEffect(() => {
    return () => {
      if (hadFocus.current) focusFallbackRef?.current?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <button
      type="button"
      className={styles.jump}
      aria-label="Jump to latest messages"
      onClick={onJump}
      onFocus={() => (hadFocus.current = true)}
      onBlur={() => (hadFocus.current = false)}
    >
      <FontAwesomeIcon icon={faChevronDown} aria-hidden="true" />
      <span>Latest</span>
    </button>
  );
};
