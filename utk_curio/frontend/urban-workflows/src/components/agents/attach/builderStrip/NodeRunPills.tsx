import React from "react";

import styles from "../AgentBuilderStrip.module.css";
import { ROW_STATE_CHIP } from "../../content/reviewCard/reviewCardText";
import { STATUS_LABEL, type SolveWaitingRow } from "./builderStripDerived";

/** One pill per plan node: its name, one label, and the per-node Solve. The
 * label is whose turn it is when the node waits (dev/131): a node that waits
 * for you to pick its source reads Needs a source, in the plan card's words,
 * with the waiting dot; one that waits upstream says so. Else it is the node's
 * live or persisted status in words. */
export const NodeRunPills: React.FC<{
  entries: Array<[string, string]>;
  userBlockedIds: Set<string>;
  solveWaiting?: SolveWaitingRow[];
  solveRunning: boolean;
  nodeSolving: string | null;
  onSolveNode?: (nodeId: string) => void;
  /** The name a node's header shows; its short id when it is not on the canvas. */
  nodeNameOf: (nodeId: string) => string;
}> = ({ entries, userBlockedIds, solveWaiting, solveRunning, nodeSolving, onSolveNode, nodeNameOf }) => (
  <ul className={styles.nodeRuns} aria-live="polite" aria-label="Plan node progress">
    {entries.map(([nodeId, status]) => {
      const name = nodeNameOf(nodeId);
      const needsUser = userBlockedIds.has(nodeId);
      const waiting = (solveWaiting ?? []).find((w) => w.nodeId === nodeId);
      return (
        <li key={nodeId} className={styles.nodeRun}>
          {needsUser ? <span className={styles.waitingDot} aria-hidden="true" /> : null}
          <span className={styles.nodeName} data-tooltip={name}>{name}</span>
          {needsUser ? (
            <span className={styles.needsSource} data-tooltip={waiting?.reason ?? undefined}>
              {ROW_STATE_CHIP["awaiting-source"]}
            </span>
          ) : waiting && waiting.kind === "upstream" ? (
            <span className={styles.waitingUpstream} data-tooltip={waiting.reason ?? undefined}>
              waiting upstream
            </span>
          ) : (
            <span className={styles[`status_${status}` as keyof typeof styles] ?? ""}>{STATUS_LABEL[status] ?? status}</span>
          )}
          {onSolveNode && (status === "pending" || status === "failed") ? (
            <button
              type="button"
              className={styles.nodeSolve}
              aria-label={`Solve node ${name} on its own`}
              data-tooltip={
                needsUser
                  ? "This node waits for you to pick its source on its card, with Use this source"
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
