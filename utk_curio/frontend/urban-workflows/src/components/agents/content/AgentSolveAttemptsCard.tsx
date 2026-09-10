import React from "react";
import type {
  AgentSolveAttemptRow,
  AgentSolveAttemptsPart,
} from "../../../api/agentsApi";
import { AgentCodeBlock } from "./AgentCodeBlock";
import styles from "./AgentSolveAttemptsCard.module.css";

/** dev/127: the bound that ended the loop, in words. Mirrors the server's own
 *  STOPPED_BY_PHRASES so the card and the failure sentence agree. */
const STOPPED_BY: Record<string, string> = {
  rounds: "the round cap was reached",
  budget: "this node's time budget was spent",
  repeat: "the builder repeated itself",
  decline: "the builder declined — it needs something from you",
  generation: "the builder could not be reached",
  blocker: "an upstream node blocked it",
  infrastructure: "the sandbox was unreachable",
  source: "a source you must confirm",
  passed: "it passed",
};

export function stoppedByPhrase(stoppedBy?: string): string {
  return STOPPED_BY[stoppedBy ?? ""] ?? "";
}

/** One attempt's summary line: "Round 3 · execution-error · 4.1 s". */
function attemptHeading(row: AgentSolveAttemptRow): string {
  const bits = [`Round ${row.round}`, row.kind || row.verdict];
  if (typeof row.durationMs === "number" && row.durationMs > 0) {
    bits.push(`${(row.durationMs / 1000).toFixed(1)} s`);
  }
  return bits.join(" · ");
}

/**
 * dev/127: every attempt a repair loop made, in the chat transcript — the
 * owner's requirement, verbatim: *"it is important to clearly display all
 * attempts to fix in the chat transcript"*, with *"the code it attempted to
 * execute alongside the error message"*.
 *
 * One native `<details>` per attempt (keyboard-operable, announced, and
 * summarizable without expanding), the last one open because it is the state
 * the node is in. Every string arrives bounded and plain-text from the runtime
 * and renders as text (`REQ-SEC-002`); the code goes through dev/78's block so
 * it can be copied the same way every other code block can.
 */
export const AgentSolveAttemptsCard: React.FC<{
  part: AgentSolveAttemptsPart;
  tintClassName?: string;
  /** Open the node's own agent chat, where the child's replies live. */
  onOpenChat?: (attachmentId: string) => void;
}> = ({ part, tintClassName, onOpenChat }) => {
  const attempts = part.attempts ?? [];
  const phrase = stoppedByPhrase(part.stoppedBy);
  const label = part.label || part.nodeId;

  return (
    <div
      className={styles.card}
      role="group"
      aria-label={`Attempts to fix ${label}`}
    >
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span className={styles.title}>{label}</span>
        <span className={styles.kind}>
          {attempts.length} attempt{attempts.length === 1 ? "" : "s"}
          {phrase ? ` · ${phrase}` : ""}
        </span>
      </div>
      <ul className={styles.rows}>
        {attempts.map((row, index) => (
          <li key={`${row.round}-${index}`}>
            <details open={index === attempts.length - 1}>
              <summary className={styles.summary}>
                <span className={styles.round}>{attemptHeading(row)}</span>
                {row.error ? (
                  <span className={styles.errorHead}>{row.error.split("\n")[0]}</span>
                ) : null}
              </summary>
              {row.error ? (
                <p className={styles.error}>
                  {row.error}
                  {row.errorTruncated ? " …" : ""}
                </p>
              ) : null}
              {row.code ? (
                <>
                  <div className={styles.codeLabel}>
                    {row.codeIsProse
                      ? "What the builder said instead of writing code"
                      : "The code this attempt ran"}
                    {row.codeTruncated ? " (truncated)" : ""}
                  </div>
                  {row.codeIsProse ? (
                    <p className={styles.prose}>{row.code}</p>
                  ) : (
                    <AgentCodeBlock>
                      <code>{row.code}</code>
                    </AgentCodeBlock>
                  )}
                </>
              ) : null}
            </details>
          </li>
        ))}
      </ul>
      {part.elided ? (
        <div className={styles.note}>
          {part.elided} earlier attempt{part.elided === 1 ? "" : "s"} not shown.
        </div>
      ) : null}
      {part.attachmentId && onOpenChat ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.open}
            aria-label={`Open the Node Builder for ${label}`}
            title="Opens this node's own agent, where the generated replies live and where you can ask for a different approach."
            onClick={() => onOpenChat(part.attachmentId as string)}
          >
            Open Node Builder
          </button>
        </div>
      ) : null}
    </div>
  );
};
