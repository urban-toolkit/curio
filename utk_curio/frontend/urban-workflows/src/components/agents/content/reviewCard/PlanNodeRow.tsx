import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";

import styles from "../AgentReviewCard.module.css";
import { ROW_STATE_CHIP } from "./reviewCardText";

/** One node of a landed plan (dev/71's lifecycle): its goal, its dependencies
 * by name, and Solve then Run, as its code is written and checked. */
export const PlanNodeRow: React.FC<{
  node: { ref: string; nodeType: string; title: string; intent: string; expects?: string; scenario?: string };
  /** The plan placed it. */
  applied: boolean;
  /** dev/71: dependency labels + readiness. */
  deps: string[];
  state: string;
  solvable: boolean;
  solveBlocker: string | null;
  /** #662: its scenario, the node a copy copies, its widgets. */
  extras?: string[];
  onSolve?: () => Promise<void>;
  onRun?: () => Promise<void>;
  /** dev/72: opens the chat that holds its validated code's change. */
  onOpenChange?: () => void;
  changeAgentName?: string;
}> = ({ node, applied, deps, state, solvable, solveBlocker, extras, onSolve, onRun, onOpenChange, changeAgentName }) => {
  // #662: a copy has its original's title; its scenario tells them apart.
  const label = node.scenario ? `${node.title} (${node.scenario})` : node.title;
  const [rowBusy, setRowBusy] = useState<"solve" | "run" | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const act = async (kind: "solve" | "run", fn?: () => Promise<void>) => {
    if (!fn || rowBusy) return;
    setRowBusy(kind);
    setRowError(null);
    try {
      await fn();
    } catch (e) {
      setRowError(e instanceof Error ? e.message : `The ${kind} failed`);
    } finally {
      setRowBusy(null);
    }
  };

  const agentName = changeAgentName ?? "the node agent";
  return (
    <li className={styles.planNodeRow}>
      <div className={styles.planNodeHead}>
        <span className={styles.planNodeTitle}>{node.title}</span>
        <span className={styles.planNodeType}>{node.nodeType}</span>
        {!applied ? (
          <span className={styles.planEdgeRefused}>Not placed</span>
        ) : (
          <>
            {ROW_STATE_CHIP[state] ? (
              <span className={state === "failed" ? styles.planEdgeRefused : styles.planNodeCreated}>
                {ROW_STATE_CHIP[state]}
                {/* dev/72: the icon-link to the chat that holds its code's
                    change (and the Solve trace). */}
                {onOpenChange ? (
                  <button
                    type="button"
                    className={styles.reviewLink}
                    aria-label={`Open ${agentName}'s chat`}
                    data-tooltip={`Open ${agentName}'s chat`}
                    onClick={onOpenChange}
                  >
                    <FontAwesomeIcon icon={faRobot} />
                  </button>
                ) : null}
              </span>
            ) : (
              <span className={styles.planNodeCreated}>Placed ✓</span>
            )}
            {onSolve && (state === "created" || state === "failed") ? (
              <button
                type="button"
                className={styles.apply}
                disabled={rowBusy !== null || !solvable}
                data-tooltip={solveBlocker ?? undefined}
                onClick={() => void act("solve", onSolve)}
                aria-label={`Solve node ${label}`}
              >
                {rowBusy === "solve" ? "Solving…" : "Solve"}
              </button>
            ) : null}
            {onRun && (state === "validated" || state === "approved") ? (
              <button
                type="button"
                className={styles.run}
                disabled={rowBusy !== null}
                onClick={() => void act("run", onRun)}
                aria-label={`Run through node ${label}`}
              >
                {rowBusy === "run" ? "Running…" : "Run"}
              </button>
            ) : null}
          </>
        )}
      </div>
      {deps.length ? <div className={styles.planNodeExpects}>needs: {deps.join(", ")}</div> : null}
      {node.expects ? <div className={styles.planNodeExpects}>{node.expects}</div> : null}
      {(extras ?? []).map((line) => (
        <div key={line} className={styles.planNodeExpects}>
          {line}
        </div>
      ))}
      <div className={styles.planNodeExpects}>{node.intent}</div>
      {rowError ? <div className={styles.error}>{rowError}</div> : null}
    </li>
  );
};
