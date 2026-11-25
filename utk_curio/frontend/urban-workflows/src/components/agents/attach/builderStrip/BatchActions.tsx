import React from "react";

import styles from "../AgentBuilderStrip.module.css";

/** One of the batch's controls: Solve (or Retry), Stop, Run workflow. */
export type BatchPart = "solve" | "stop" | "run";

const ALL_PARTS: readonly BatchPart[] = ["solve", "stop", "run"];

/** Solve / Retry, Stop (dev/131: the control ends a SESSION that keeps
 * managing the dataflow, and everything already written stays) and Run
 * workflow, each explaining its disabled state. The plan line holds the one
 * that is its main action, `inline`; the more part holds the others. */
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
  /** Which controls to draw; all three by default. */
  parts?: readonly BatchPart[];
  /** Drawn in the plan line's own row, with no row of their own. */
  inline?: boolean;
}> = ({
  phase,
  solveRunning,
  solveDisabledReason,
  unresolved,
  failedCount,
  pendingCount,
  cancelling,
  runDisabledReason,
  isRunActive,
  onSolve,
  onCancel,
  onRun,
  parts = ALL_PARTS,
  inline = false,
}) => {
  const buttons = (
    <>
      {parts.includes("solve") ? (
        <button
          type="button"
          className={styles.solve}
          disabled={solveRunning || Boolean(solveDisabledReason)}
          data-tooltip={
            solveDisabledReason ??
            (phase === "interrupted"
              ? "A new execution linked to the interrupted one; nothing is replayed"
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
      ) : null}
      {parts.includes("stop") && onCancel && solveRunning ? (
        <button
          type="button"
          className={styles.run}
          disabled={cancelling}
          data-tooltip="Ends the session after the current node finishes (a running fetch cannot be aborted). Everything already written stays."
          onClick={onCancel}
        >
          {cancelling ? "Stopping…" : "Stop"}
        </button>
      ) : null}
      {parts.includes("run") ? (
        <button
          type="button"
          className={styles.run}
          disabled={phase !== "ready" || Boolean(runDisabledReason) || isRunActive}
          data-tooltip={runDisabledReason ?? (isRunActive ? "A run is already in progress" : undefined)}
          onClick={onRun}
        >
          Run workflow
        </button>
      ) : null}
    </>
  );
  return inline ? buttons : <div className={styles.actions}>{buttons}</div>;
};
