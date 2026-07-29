import React, { useState } from "react";
import type { AgentProposalPart } from "../../../api/agentsApi";
import styles from "./AgentReviewCard.module.css";

const OUTCOME_LABEL: Record<string, string> = {
  applied: "Applied",
  dismissed: "Dismissed",
  superseded: "Superseded by a newer proposal",
  stale: "The node changed since this was proposed — ask the agent to propose again",
};

/**
 * The review-before-apply card (memo dev/41; the blueprint's planned
 * `AgentReviewCard`). The agent proposes; the USER confirms here — Apply and
 * Dismiss are system review controls (the sanctioned exception family to
 * "no agent action buttons", same as the DEC-035 install dialog). The
 * proposed content is model output: it renders as inert plain text
 * (REQ-SEC-002), never markup. Non-pending proposals render inert with
 * their outcome label.
 */
export const AgentReviewCard: React.FC<{
  part: AgentProposalPart;
  /** Tint class carrying the agent's category color for the accent dot. */
  tintClassName?: string;
  onApply?: (proposalId: string) => Promise<void>;
  onDismiss?: (proposalId: string) => Promise<void>;
}> = ({ part, tintClassName, onApply, onDismiss }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (fn?: (proposalId: string) => Promise<void>) => {
    if (!fn || busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn(part.proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The review action failed");
    } finally {
      setBusy(false);
    }
  };

  const pending = part.status === "pending";
  return (
    <div className={styles.card} role="group" aria-label={`Review proposal: ${part.summary}`}>
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span>{part.summary}</span>
        <span className={styles.kind}>review</span>
      </div>
      <div className={styles.preview}>{part.preview}</div>
      {pending && (onApply || onDismiss) ? (
        <div className={styles.actions}>
          {onApply ? (
            <button
              type="button"
              className={styles.apply}
              disabled={busy}
              onClick={() => void act(onApply)}
            >
              {busy ? "Applying…" : "Apply"}
            </button>
          ) : null}
          {onDismiss ? (
            <button
              type="button"
              className={styles.dismiss}
              disabled={busy}
              onClick={() => void act(onDismiss)}
            >
              Dismiss
            </button>
          ) : null}
        </div>
      ) : !pending ? (
        <div
          className={`${styles.outcome} ${
            styles[`outcome_${part.status}` as keyof typeof styles] ?? ""
          }`}
        >
          {OUTCOME_LABEL[part.status] ?? part.status}
        </div>
      ) : null}
      {error ? <div className={styles.error}>{error}</div> : null}
    </div>
  );
};
