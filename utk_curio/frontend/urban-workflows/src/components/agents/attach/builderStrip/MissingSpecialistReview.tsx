import React from "react";

import type { AgentProposalSummary } from "../../../../services/agents";
import styles from "../AgentBuilderStrip.module.css";

/** dev/106: the missing-specialist review, from the mirror — Solve minted a
 * reviewed `project.install` (REQ-ORCH-001) and this is where the failure is,
 * so this is where Install lives. */
export const MissingSpecialistReview: React.FC<{
  review: AgentProposalSummary;
  reviewBusy: boolean;
  solving: boolean;
  onApply?: () => void;
  onDismiss?: () => void;
}> = ({ review, reviewBusy, solving, onApply, onDismiss }) => (
  <div className={styles.actions} role="group" aria-label="Missing specialist">
    <span className={styles.reviewSummary}>Solve needs a specialist — {review.summary}</span>
    {onApply ? (
      <button type="button" className={styles.solve} disabled={reviewBusy || solving} onClick={onApply}>
        {reviewBusy ? "Adding…" : "Add to project"}
      </button>
    ) : null}
    {onDismiss ? (
      <button type="button" className={styles.run} disabled={reviewBusy} onClick={onDismiss}>
        Dismiss
      </button>
    ) : null}
  </div>
);
