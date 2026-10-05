import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import { countLabel } from "../../../../utils/countLabel";
import styles from "../AgentReviewCard.module.css";
import { removalsTitle } from "./reviewCardText";

/** A dataflow plan's summary (dev/52: counts + goal at a glance) and, when the
 * plan removes anything, DEC-049.2's removals block — every victim by NAME
 * with a content flag; dev/112: removed CONNECTIONS named too. */
export const PlanSummary: React.FC<{ part: AgentProposalPart }> = ({ part }) => {
  if (part.tool !== "dataflow.plan.write" || !part.plan) return null;
  const plan = part.plan;
  const removes = (plan.removals?.length ?? 0) > 0 || (plan.removedEdges?.length ?? 0) > 0;
  return (
    <>
      <div className={styles.meta}>
        {countLabel(plan.nodes.length, "node")} · {countLabel(plan.edgeCount, "connection")}
        {plan.scenarios?.length ? ` · ${countLabel(plan.scenarios.length, "scenario")}` : ""} · {plan.goal}
      </div>
      {removes ? (
        <div className={styles.removals} role="group" aria-label="Nodes and connections this plan removes">
          <div className={styles.removalsTitle}>
            {removalsTitle(plan.removals?.length ?? 0, plan.removedEdges?.length ?? 0, plan.cascadeCount ?? 0)}
          </div>
          <ul className={styles.removalsList}>
            {(plan.removals ?? []).map((victim) => (
              <li key={victim.id}>
                {victim.label}
                {victim.nodeType ? ` · ${victim.nodeType}` : ""}
                {victim.contentChars > 0 ? ` (contains ${victim.contentChars} chars of content)` : " (empty)"}
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
        </div>
      ) : null}
    </>
  );
};
