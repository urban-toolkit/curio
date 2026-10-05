import React from "react";

import type { AgentProposalSummary } from "../../../../services/agents";
import styles from "../AgentBuilderStrip.module.css";

/** The pending plan review's controls, where the phase indicator points
 * (dev/53). dev/67-9 (DEC-054): the validated sequence is the DEFAULT; bulk
 * apply survives only as the explicit secondary action. */
export const PlanReviewActions: React.FC<{
  review: AgentProposalSummary;
  paused: boolean;
  simBusy: "step" | "auto" | null;
  reviewBusy: boolean;
  onSimulate?: (mode: "step" | "auto") => void;
  onCancelSimulate?: () => void;
  onApply?: () => void;
  onDismiss?: () => void;
}> = ({ review, paused, simBusy, reviewBusy, onSimulate, onCancelSimulate, onApply, onDismiss }) => (
  <div className={styles.actions} role="group" aria-label="Plan review">
    <span className={styles.reviewSummary}>{review.summary}</span>
    {onSimulate ? (
      <>
        <button type="button" className={styles.solve} disabled={simBusy !== null || reviewBusy} onClick={() => onSimulate("auto")}>
          {simBusy === "auto" ? "Building…" : paused ? "Resume" : "Build & validate plan"}
        </button>
        <button type="button" className={styles.run} disabled={simBusy !== null || reviewBusy} onClick={() => onSimulate("step")}>
          {simBusy === "step" ? "Stepping…" : "Step"}
        </button>
      </>
    ) : null}
    {simBusy && onCancelSimulate ? (
      <button type="button" className={styles.run} onClick={onCancelSimulate}>
        Cancel
      </button>
    ) : null}
    {onApply ? (
      <button type="button" className={styles.run} disabled={reviewBusy || simBusy !== null} onClick={onApply}>
        {reviewBusy ? "Applying…" : onSimulate ? "Apply all without validation" : "Apply plan"}
      </button>
    ) : null}
    {onDismiss ? (
      <button type="button" className={styles.run} disabled={reviewBusy} onClick={onDismiss}>
        Dismiss
      </button>
    ) : null}
  </div>
);
