import React from "react";

import styles from "../AgentReviewCard.module.css";
import { PlanEdgesList } from "./PlanEdgesList";
import { PlanScenariosList } from "./PlanScenariosList";
import { planNodeExtras, templateLabelOf, type PlanDisplay, type PlanNodeReviewState } from "./reviewCardText";

/** A landed plan's Details, behind its card's Details: the goal it set, its
 * checks and the agents it put on its nodes, each node's kind, what it reads
 * and writes, and its extras, its connections and its scenarios. Each row of
 * the card keeps the node's name, what it does and its state. */
export const PlanDetails: React.FC<{
  part: PlanDisplay & { lines?: string[]; checks?: string[]; goalSet?: string };
  planNodeState?: PlanNodeReviewState;
  id: string;
}> = ({ part, planNodeState, id }) => {
  const plan = part.plan!;
  // A card from before its checks were worded for a person says what the
  // agents read.
  const checks = part.checks ?? part.lines ?? [];
  return (
    <div id={id} className={styles.planDetails} role="group" aria-label="Plan details">
      {part.goalSet ? (
        <div>{`Goal set to: ${part.goalSet}`}</div>
      ) : plan.goal ? (
        <div>{plan.goal}</div>
      ) : null}
      {checks.map((line, i) => (
        <div key={`check-${i}`}>{line}</div>
      ))}
      <div className={styles.planDetailsHead}>Nodes</div>
      {plan.nodes.map((node) => (
        <div key={node.ref} className={styles.planDetailsNode}>
          <div>
            <b>{node.title}</b>
            {` · ${templateLabelOf(node.nodeType)}`}
            {node.expects ? (
              <>
                {" · "}
                <span>{node.expects}</span>
              </>
            ) : null}
          </div>
          {planNodeExtras(part, node).map((line) => (
            <div key={line} className={styles.planNodeExpects}>
              {line}
            </div>
          ))}
        </div>
      ))}
      {plan.edges?.length ? <PlanEdgesList part={part} /> : null}
      <PlanScenariosList part={part} planNodeState={planNodeState} />
    </div>
  );
};
