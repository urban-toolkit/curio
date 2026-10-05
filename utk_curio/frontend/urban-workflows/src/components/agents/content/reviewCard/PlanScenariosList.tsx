import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { planScenarioLine, type PlanNodeReviewState } from "./reviewCardText";

/** #662: the scenarios a plan saves, reviewed BY NAME like its nodes and
 * connections: each with its color, its nodes, and for a duplicate what it
 * copies and the widget values it changes. A scenario is saved once all of
 * its nodes exist, by the plan's Apply or by the per-node Apply that creates
 * the last of them; the row says when it is. */
export const PlanScenariosList: React.FC<{
  part: AgentProposalPart;
  planNodeState?: PlanNodeReviewState;
}> = ({ part, planNodeState }) => {
  const scenarios = part.plan?.scenarios ?? [];
  if (!scenarios.length) return null;
  return (
    <div className={styles.planEdges} role="group" aria-label="Scenarios this plan saves">
      <div className={styles.planEdgesHead}>
        <span>Scenarios</span>
      </div>
      <ul className={styles.planEdgesList}>
        {scenarios.map((scenario, index) => {
          const state = planNodeState?.scenarioStates?.[String(index)];
          return (
            <li key={scenario.name} className={styles.planScenarioRow} aria-label={`Scenario ${scenario.name}`}>
              <span
                className={styles.planScenarioSwatch}
                style={{ "--scenario-color": scenario.color } as React.CSSProperties}
                aria-hidden="true"
              />
              <span className={styles.planScenarioText}>
                <span className={styles.planScenarioName}>{scenario.name}</span>
                <span className={styles.planNodeExpects}>{planScenarioLine(scenario)}</span>
                {scenario.description ? (
                  <span className={styles.planNodeExpects}>{scenario.description}</span>
                ) : null}
              </span>
              {state === "applied" ? (
                <span className={styles.planNodeCreated}>Saved ✓</span>
              ) : state === "refused" ? (
                <span className={styles.planEdgeRefused}>Not saved ✗</span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
};
