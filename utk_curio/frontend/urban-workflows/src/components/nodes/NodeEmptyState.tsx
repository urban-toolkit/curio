import React, { memo } from "react";
import {
  NODE_EMPTY_COPY,
  type NodeEmptyReason,
} from "../../utils/nodeEmptyState";
import styles from "./NodeEmptyState.module.css";

export interface NodeEmptyStateProps {
  reason: NodeEmptyReason;
  /** Overrides the standard hint where a node can say something more specific. */
  hint?: string;
}

/**
 * What a node body shows when it has nothing to show (#224).
 *
 * Shared rather than per-node, because the reported symptom was that the states
 * are indistinguishable: an unconnected node, a node whose upstream has not run
 * and a genuinely broken one all rendered the same blank rectangle. Saying
 * which of those it is only helps if every node says it the same way.
 *
 * Lives beside SaveOutputToggle, which is where shared node chrome lives.
 */
export const NodeEmptyState = memo(function NodeEmptyState({
  reason,
  hint,
}: NodeEmptyStateProps) {
  const copy = NODE_EMPTY_COPY[reason];
  return (
    <div className={styles.root} data-curio-node-empty={reason}>
      <span className={styles.title}>{copy.title}</span>
      {hint ?? copy.hint ? (
        <span className={styles.hint}>{hint ?? copy.hint}</span>
      ) : null}
    </div>
  );
});

export default NodeEmptyState;
