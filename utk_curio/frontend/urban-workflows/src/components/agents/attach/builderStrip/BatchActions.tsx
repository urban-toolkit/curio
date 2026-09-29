import React from "react";

import styles from "../AgentBuilderStrip.module.css";

/** Solve / Retry, Stop (dev/131: the control ends a SESSION that keeps
 * managing the dataflow, and everything already written stays) and Run
 * workflow, each explaining its disabled state. */
export const BatchActions: React.FC<{
  phase: string;
  solveRunning: boolean;
  solveDisabledReason: string | null;
  unresolved: number;
  failedCount: number;
  pendingCount: number;
  cancelling: boolean;
  runDisabledReason: string | null;
  isRunActive: boolean;
  onSolve: () => void;
  onCancel?: () => void;
  onRun: () => void;
}> = ({ phase, solveRunning, solveDisabledReason, unresolved, failedCount, pendingCount, cancelling, runDisabledReason, isRunActive, onSolve, onCancel, onRun }) => (
  <div className={styles.actions}>
    <button
      type="button"
      className={styles.solve}
      disabled={solveRunning || Boolean(solveDisabledReason)}
      title={
        solveDisabledReason ??
        (phase === "interrupted"
          ? "A new execution linked to the interrupted one — nothing is replayed"
          : "Data-loading nodes run in the sandbox and are fixed before their code is written")
      }
      onClick={onSolve}
    >
      {solveRunning
        ? "Solving…"
        : phase === "interrupted"
          ? `Retry ${unresolved} interrupted`
          : failedCount && !pendingCount
            ? `Retry ${failedCount} failed`
            : "Solve"}
    </button>
    {onCancel && solveRunning ? (
      <button
        type="button"
        className={styles.run}
        disabled={cancelling}
        title="Ends the session after the current node finishes — a running fetch cannot be aborted. Everything already written stays."
        onClick={onCancel}
      >
        {cancelling ? "Stopping…" : "Stop"}
      </button>
    ) : null}
    <button
      type="button"
      className={styles.run}
      disabled={phase !== "ready" || Boolean(runDisabledReason) || isRunActive}
      title={runDisabledReason ?? (isRunActive ? "A run is already in progress" : undefined)}
      onClick={onRun}
    >
      Run workflow
    </button>
  </div>
);
