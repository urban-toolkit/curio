import React from "react";

import { AgentRunStatusLine } from "../AgentRunStatusLine";
import styles from "../AgentBuilderStrip.module.css";
import { PHASES, PHASE_RANK } from "./builderStripDerived";

/** The phase chips (Plan → Review → Solve → Ready) and, while a batch runs,
 * the shared running-status line (dev/83) beside them. */
export const PhaseChips: React.FC<{
  phase: string;
  activeBatchLabel: string | null;
  batchStartedAt: number | null;
  batchDetail?: string;
}> = ({ phase, activeBatchLabel, batchStartedAt, batchDetail }) => (
  <div className={styles.phases} aria-label="Phase">
    {PHASES.map((p) => (
      <span
        key={p.id}
        className={`${styles.phaseChip} ${PHASE_RANK[phase] === PHASE_RANK[p.id] ? styles.phaseActive : ""}`}
        aria-current={PHASE_RANK[phase] === PHASE_RANK[p.id] ? "step" : undefined}
      >
        {p.label}
      </span>
    ))}
    {activeBatchLabel && batchStartedAt !== null ? (
      <AgentRunStatusLine
        display={{ kind: "running", startedAt: batchStartedAt }}
        runningLabel={activeBatchLabel}
        runningDetail={batchDetail}
        srLabel="Solve batch running"
      />
    ) : null}
  </div>
);
