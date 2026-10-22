import React from "react";

import styles from "../AgentBuilderStrip.module.css";
import { STATUS_LABEL, type SolveWaitingRow } from "./builderStripDerived";

/** One pill per plan node: its live or persisted status in words, whose turn
 * it is (dev/131: "needs you" / "waiting upstream"), and the per-node Solve. */
export const NodeRunPills: React.FC<{
  entries: Array<[string, string]>;
  userBlockedIds: Set<string>;
  solveWaiting?: SolveWaitingRow[];
  solveRunning: boolean;
  nodeSolving: string | null;
  onSolveNode?: (nodeId: string) => void;
  /** The name of the agent an attachment of this dataflow binds, from the live list. */
  agentNameOf?: (attachmentId: string) => string | null;
}> = ({ entries, userBlockedIds, solveWaiting, solveRunning, nodeSolving, onSolveNode, agentNameOf }) => (
  <ul className={styles.nodeRuns} aria-live="polite" aria-label="Plan node progress">
    {entries.map(([nodeId, status]) => {
      const needsUser = userBlockedIds.has(nodeId);
      const waiting = (solveWaiting ?? []).find((w) => w.nodeId === nodeId);
      // The node's own agent that holds its candidates, by its manifest's name.
      const finder = waiting?.attachmentId ? agentNameOf?.(waiting.attachmentId) ?? null : null;
      return (
        <li key={nodeId} className={`${styles.nodeRun}${needsUser ? ` ${styles.nodeNeedsUser}` : ""}`}>
          <span className={styles.nodeId}>{nodeId.slice(0, 8)}</span>
          <span className={styles[`status_${status}` as keyof typeof styles] ?? ""}>{STATUS_LABEL[status] ?? status}</span>
          {needsUser ? (
            <span className={styles.needsYou} data-tooltip={waiting?.reason ?? undefined}>
              needs you
            </span>
          ) : null}
          {waiting && waiting.kind === "upstream" ? (
            <span className={styles.waitingUpstream} data-tooltip={waiting.reason ?? undefined}>
              waiting upstream
            </span>
          ) : null}
          {onSolveNode && (status === "pending" || status === "failed") ? (
            <button
              type="button"
              className={styles.nodeSolve}
              aria-label={`Solve node ${nodeId.slice(0, 8)} on its own`}
              data-tooltip={
                needsUser
                  ? `This node is waiting for you to confirm a source: open its ${finder ?? "candidates"} first`
                  : "Runs this node's own agent: generate, run in the sandbox, fix, and write only code that passed"
              }
              disabled={needsUser || solveRunning || nodeSolving === nodeId}
              onClick={() => onSolveNode(nodeId)}
            >
              {nodeSolving === nodeId ? "Solving…" : "Solve"}
            </button>
          ) : null}
        </li>
      );
    })}
  </ul>
);
