import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { MADE_BEFORE_DIRECT_EDITS, OUTCOME_LABEL, WAITS_FOR_OWNER } from "./reviewCardText";

/** Apply and Dismiss are system review controls (the sanctioned exception
 * family to "no agent action buttons"); a non-pending proposal renders inert
 * with its outcome label. An install on an invited editor's chat waits for
 * the dataflow owner's review, which the card says instead (`waitsForOwner`).
 * A review of a change saved before agents changed the dataflow directly
 * (`madeBefore`) says so, with Dismiss alone. */
export const ReviewActions: React.FC<{
  part: AgentProposalPart;
  busy: boolean;
  onApply?: () => void;
  onDismiss?: () => void;
  waitsForOwner?: boolean;
  madeBefore?: boolean;
}> = ({ part, busy, onApply, onDismiss, waitsForOwner = false, madeBefore = false }) => {
  const pending = part.status === "pending";
  if (pending && waitsForOwner) {
    return <div className={styles.outcome} data-curio-waits-for-owner="true">{WAITS_FOR_OWNER}</div>;
  }
  if (pending && madeBefore) {
    return (
      <>
        <div className={styles.outcome} data-curio-made-before="true">{MADE_BEFORE_DIRECT_EDITS}</div>
        {onDismiss ? (
          <div className={styles.actions}>
            <button type="button" className={styles.dismiss} disabled={busy} onClick={onDismiss}>
              Dismiss
            </button>
          </div>
        ) : null}
      </>
    );
  }
  if (pending && (onApply || onDismiss)) {
    return (
      <div className={styles.actions}>
        {onApply ? (
          <button type="button" className={styles.apply} disabled={busy} onClick={onApply}>
            {busy ? "Applying…" : "Apply"}
          </button>
        ) : null}
        {onDismiss ? (
          <button type="button" className={styles.dismiss} disabled={busy} onClick={onDismiss}>
            Dismiss
          </button>
        ) : null}
      </div>
    );
  }
  if (!pending) {
    return (
      <div className={`${styles.outcome} ${styles[`outcome_${part.status}` as keyof typeof styles] ?? ""}`}>
        {OUTCOME_LABEL[part.status] ?? part.status}
      </div>
    );
  }
  return null;
};
