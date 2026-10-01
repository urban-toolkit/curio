import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { OUTCOME_LABEL } from "./reviewCardText";

/** Apply and Dismiss are system review controls (the sanctioned exception
 * family to "no agent action buttons"); a non-pending proposal renders inert
 * with its outcome label. */
export const ReviewActions: React.FC<{
  part: AgentProposalPart;
  busy: boolean;
  onApply?: () => void;
  onDismiss?: () => void;
}> = ({ part, busy, onApply, onDismiss }) => {
  const pending = part.status === "pending";
  if (pending && (onApply || onDismiss)) {
    return (
      <div className={styles.actions}>
        {onApply ? (
          <button type="button" className={styles.apply} disabled={busy} onClick={onApply}>
            {busy ? "Applying…" : part.validation?.verdict === "fail" ? "Apply anyway" : "Apply"}
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
