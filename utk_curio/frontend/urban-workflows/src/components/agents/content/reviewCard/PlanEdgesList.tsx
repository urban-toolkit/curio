import React from "react";

import styles from "../AgentReviewCard.module.css";
import type { PlanDisplay } from "./reviewCardText";

/** The connections a landed plan drew, BY NAME in a vertical list: you always
 * know which two nodes each one connects. */
export const PlanEdgesList: React.FC<{ part: PlanDisplay }> = ({ part }) => (
  <div className={styles.planEdges} role="group" aria-label="Planned connections">
    <div className={styles.planEdgesHead}>
      <span>Connections</span>
    </div>
    <ul className={styles.planEdgesList}>
      {(part.plan?.edges ?? []).map((edge, index) => {
        const names =
          `${edge.fromLabel} ${edge.kind === "interaction" ? "⇄" : "→"} ${edge.toLabel}` +
          (edge.toHandle ? ` [${edge.toHandle}]` : "") +
          (edge.kind === "interaction" ? " · interaction" : "");
        return (
          <li key={index} className={styles.planEdgeRow}>
            {/* Wraps rather than cut: two rows to different targets
                used to read the same (#511). */}
            <span className={styles.planEdgeNames} data-tooltip={names}>
              {names}
            </span>
          </li>
        );
      })}
    </ul>
  </div>
);
