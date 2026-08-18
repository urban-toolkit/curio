import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck, faTriangleExclamation } from "@fortawesome/free-solid-svg-icons";
import type { RunStatusDisplay } from "./agentRunStatus";
import { formatDuration, formatTokenCount } from "./agentRunStatus";
import { useRunTicker } from "./useRunTicker";
import styles from "./AgentRunStatusLine.module.css";

/**
 * Compact execution status for ONE agent reply (memo dev/80; per-message per
 * the dev/80 amendment) — rendered beneath the reply bubble.
 *
 * running: pulsing dot + rotating label + elapsed ("Cooking… · 0:12")
 * done:    "✓ Finished in 12s · 1.4k tokens" — this reply's own duration and
 *          Actual tokens (+ the review chip when a proposal awaits the user)
 * error:   "Failed after 8s" (the error turn itself keeps the message)
 *
 * The container is a polite live region announcing phase transitions only:
 * the visible spans are aria-hidden (the per-second elapsed and the label
 * rotation must not spam screen readers); a visually-hidden span carries the
 * phase text.
 */
export const AgentRunStatusLine: React.FC<{
  display: RunStatusDisplay;
  /** Category tint class — colors the live dot via currentColor. */
  tintClassName?: string;
}> = ({ display, tintClassName }) => {
  const { elapsedLabel, processingLabel } = useRunTicker(
    display.kind === "running" ? display.startedAt : null,
  );

  if (display.kind === "running") {
    return (
      <span className={styles.line} role="status" aria-live="polite">
        <span className={styles.srOnly}>Agent is working</span>
        <span className={`${styles.dot} ${tintClassName ?? ""}`} aria-hidden="true" />
        <span className={styles.text} aria-hidden="true">
          {processingLabel}… · {elapsedLabel}
        </span>
      </span>
    );
  }

  if (display.kind === "error") {
    const text =
      display.durationMs != null
        ? `Failed after ${formatDuration(display.durationMs)}`
        : "Failed";
    return (
      <span className={`${styles.line} ${styles.error}`} role="status" aria-live="polite">
        <span className={styles.srOnly}>Run failed</span>
        <FontAwesomeIcon icon={faTriangleExclamation} className={styles.icon} aria-hidden="true" />
        <span className={styles.text} aria-hidden="true">
          {text}
        </span>
      </span>
    );
  }

  const tokens = display.usage
    ? (display.usage.inputTokens ?? 0) + (display.usage.outputTokens ?? 0)
    : 0;
  const finished =
    display.durationMs != null ? `Finished in ${formatDuration(display.durationMs)}` : "Finished";
  const text = tokens > 0 ? `${finished} · ${formatTokenCount(tokens)} tokens` : finished;
  // This reply's own in/out breakdown on hover (the cumulative counter by
  // the composer carries the session total).
  const breakdown = display.usage
    ? `${display.usage.inputTokens.toLocaleString()} in / ${display.usage.outputTokens.toLocaleString()} out — provider-reported`
    : undefined;
  return (
    <span className={`${styles.line} ${styles.done}`} role="status" aria-live="polite">
      <span className={styles.srOnly}>Run finished</span>
      <FontAwesomeIcon icon={faCheck} className={styles.icon} aria-hidden="true" />
      <span className={styles.text} aria-hidden="true" title={breakdown}>
        {text}
      </span>
      {display.pendingReview ? (
        <span className={styles.reviewChip}>Awaiting your review</span>
      ) : null}
    </span>
  );
};
