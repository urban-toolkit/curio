import React from "react";

import type { AgentProposalSummary } from "../../../../services/agents";
import styles from "../AgentBuilderStrip.module.css";

/** The landed plan's controls, in the plan line's more part (dev/53): Build &
 * validate fills its nodes in plan order (dev/67-9, DEC-054), Step does one
 * action, and Cancel stops a build that runs. A paused build resumes from the
 * line's Resume, so its button is drawn only *withBuild*. */
export const PlanBuildActions: React.FC<{
  plan: AgentProposalSummary;
  paused: boolean;
  simBusy: "step" | "auto" | null;
  /** Draw Build & validate plan (Resume while paused); the line holds Resume. */
  withBuild?: boolean;
  onSimulate: (mode: "step" | "auto") => void;
  onCancelSimulate?: () => void;
}> = ({ plan, paused, simBusy, withBuild = true, onSimulate, onCancelSimulate }) => (
  <div className={styles.actions} role="group" aria-label="Build the plan">
    <span className={styles.reviewSummary}>{plan.summary}</span>
    {withBuild ? (
      <button type="button" className={styles.solve} disabled={simBusy !== null} onClick={() => onSimulate("auto")}>
        {simBusy === "auto" ? "Building…" : paused ? "Resume" : "Build & validate plan"}
      </button>
    ) : null}
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
