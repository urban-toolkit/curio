import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { planEdgeRowState, type PlanNodeReviewState } from "./reviewCardText";

/** dev/67-8 (Simulation Mode: connect): edges reviewed BY NAME in a vertical
 * list — you always know which two nodes a click connects. */
export const PlanEdgesList: React.FC<{
  part: AgentProposalPart;
  planNodeState?: PlanNodeReviewState;
  /** The index being connected, "all", or null when idle. */
  edgeBusy: string | null;
  onApplyEdges: (indices?: number[]) => Promise<void>;
}> = ({ part, planNodeState, edgeBusy, onApplyEdges }) => (
  <div className={styles.planEdges} role="group" aria-label="Planned connections">
    <div className={styles.planEdgesHead}>
      <span>Connections</span>
      <button type="button" className={styles.apply} disabled={edgeBusy !== null} onClick={() => void onApplyEdges()}>
        {edgeBusy === "all" ? "Connecting…" : "Connect all"}
      </button>
    </div>
    <ul className={styles.planEdgesList}>
      {part.plan!.edges!.map((edge, index) => {
        const { state, blockedBy } = planEdgeRowState(part, edge, index, planNodeState);
        return (
          <li key={index} className={styles.planEdgeRow}>
            <span className={styles.planEdgeNames}>
              {edge.fromLabel} {edge.kind === "interaction" ? "⇄" : "→"} {edge.toLabel}
              {edge.toHandle ? ` [${edge.toHandle}]` : ""}
              {edge.kind === "interaction" ? " · interaction" : ""}
            </span>
            {state === "applied" ? (
              <span className={styles.planNodeCreated}>Connected ✓</span>
            ) : state === "refused" ? (
              <span className={styles.planEdgeRefused}>Refused ✗</span>
            ) : (
              <button
                type="button"
                className={styles.apply}
                disabled={edgeBusy !== null || blockedBy !== null}
                title={blockedBy ? `create '${blockedBy}' first` : undefined}
                aria-label={`Connect ${edge.fromLabel} to ${edge.toLabel}`}
                onClick={() => void onApplyEdges([index])}
              >
                {edgeBusy === String(index) ? "Connecting…" : "Connect"}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  </div>
);
