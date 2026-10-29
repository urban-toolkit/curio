import React from "react";

import styles from "../AgentReviewCard.module.css";
import { removalsTitle, tilesLeftLine, type PlanDisplay } from "./reviewCardText";

/** A landed plan's goal (its card's lines count what it added) and, when the
 * plan removed anything, DEC-049.2's removals block: every victim by NAME
 * with a content flag; dev/112: removed CONNECTIONS named too. */
export const PlanSummary: React.FC<{ part: PlanDisplay }> = ({ part }) => {
  if (part.tool !== "dataflow.plan.write" || !part.plan) return null;
  const plan = part.plan;
  const removes = (plan.removals?.length ?? 0) > 0 || (plan.removedEdges?.length ?? 0) > 0;
  const tilesLeft = tilesLeftLine(plan.removals ?? []);
  return (
    <>
      {plan.goal ? <div className={styles.meta}>{plan.goal}</div> : null}
      {removes ? (
        <div className={styles.removals} role="group" aria-label="Nodes and connections this plan removed">
          <div className={styles.removalsTitle}>
            {removalsTitle(plan.removals?.length ?? 0, plan.removedEdges?.length ?? 0, plan.cascadeCount ?? 0)}
          </div>
          <ul className={styles.removalsList}>
            {(plan.removals ?? []).map((victim) => (
              <li key={victim.id}>
                {victim.label}
                {victim.nodeType ? ` · ${victim.nodeType}` : ""}
                {victim.pinned ? " · dashboard tile" : ""}
                {victim.contentChars > 0 ? ` (contained ${victim.contentChars} chars of content)` : " (empty)"}
              </li>
            ))}
            {(plan.removedEdges ?? []).map((edge) => (
              <li key={edge.id}>
                {edge.kind === "interaction" ? "⇄ " : "→ "}
                {edge.fromLabel} → {edge.toLabel}
                {edge.kind === "interaction" ? " · interaction" : ""}
              </li>
            ))}
          </ul>
          {tilesLeft ? <div className={styles.meta}>{tilesLeft}</div> : null}
        </div>
      ) : null}
    </>
  );
};
