import React from "react";

import type { AgentProposalSummary } from "../../../../services/agents";
import styles from "../AgentBuilderStrip.module.css";

/** The landed plan's controls, where the phase indicator points (dev/53):
 * Build & validate fills its nodes in plan order (dev/67-9, DEC-054), Step
 * does one action, and a paused build resumes where it stopped. */
export const PlanBuildActions: React.FC<{
  plan: AgentProposalSummary;
  paused: boolean;
  simBusy: "step" | "auto" | null;
  onSimulate: (mode: "step" | "auto") => void;
  onCancelSimulate?: () => void;
}> = ({ plan, paused, simBusy, onSimulate, onCancelSimulate }) => (
  <div className={styles.actions} role="group" aria-label="Build the plan">
    <span className={styles.reviewSummary}>{plan.summary}</span>
    <button type="button" className={styles.solve} disabled={simBusy !== null} onClick={() => onSimulate("auto")}>
      {simBusy === "auto" ? "Building…" : paused ? "Resume" : "Build & validate plan"}
    </button>
    <button type="button" className={styles.run} disabled={simBusy !== null} onClick={() => onSimulate("step")}>
      {simBusy === "step" ? "Stepping…" : "Step"}
    </button>
    {simBusy && onCancelSimulate ? (
      <button type="button" className={styles.run} onClick={onCancelSimulate}>
        Cancel
      </button>
    ) : null}
  </div>
);
