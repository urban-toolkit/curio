import React from "react";

import type { AgentProposalSummary } from "../../../../services/agents";
import styles from "../AgentBuilderStrip.module.css";

/** The landed plan's controls, in the plan line's more part (dev/53): Build &
 * validate fills its nodes in plan order (dev/67-9, DEC-054), and Step does one
 * action. A running build's Stop and a paused build's Resume are the line's own
 * action, so Build & validate plan is drawn only *withBuild*. While a row's
 * Solve runs on the plan (*waitReason* says so), neither starts. */
export const PlanBuildActions: React.FC<{
  plan: AgentProposalSummary;
  paused: boolean;
  /** The build that runs, step or auto, or null. */
  simBusy: "step" | "auto" | null;
  /** Draw Build & validate plan (Resume while paused); the line holds Resume. */
  withBuild?: boolean;
  /** Why no build starts now, though none runs: a row's Solve of the plan
   *  runs on the server. Its tooltip says so. */
  waitReason?: string | null;
  onSimulate: (mode: "step" | "auto") => void;
}> = ({ plan, paused, simBusy, withBuild = true, waitReason = null, onSimulate }) => (
  <div className={styles.actions} role="group" aria-label="Build the plan">
    <span className={styles.reviewSummary}>{plan.summary}</span>
    {withBuild ? (
      <button
        type="button"
        className={styles.solve}
        disabled={simBusy !== null || Boolean(waitReason)}
        data-tooltip={simBusy === null && waitReason ? waitReason : undefined}
        onClick={() => onSimulate("auto")}
      >
        {simBusy === "auto" ? "Building…" : paused ? "Resume" : "Build & validate plan"}
      </button>
    ) : null}
    <button
      type="button"
      className={styles.run}
      disabled={simBusy !== null || Boolean(waitReason)}
      data-tooltip={simBusy === null && waitReason ? waitReason : undefined}
      onClick={() => onSimulate("step")}
    >
      {simBusy === "step" ? "Stepping…" : "Step"}
    </button>
  </div>
);
