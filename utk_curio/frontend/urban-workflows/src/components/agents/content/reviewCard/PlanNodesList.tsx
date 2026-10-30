import React from "react";

import styles from "../AgentReviewCard.module.css";
import { PlanNodeRow } from "./PlanNodeRow";
import { planNodeExtras, planNodeRowState, type PlanDisplay, type PlanNodeReviewState } from "./reviewCardText";

/** A landed plan's nodes, each inspectable: its goal, what it expects, and
 * Solve then Run as its code is written and checked. No generated code ever
 * renders here (plans are content-free by contract). */
export const PlanNodesList: React.FC<{
  part: PlanDisplay;
  planNodeState?: PlanNodeReviewState;
  onSolvePlanNode?: (ref: string) => Promise<void>;
  onRunPlanNode?: (ref: string) => Promise<void>;
  onOpenAgentChat?: (attachmentId: string) => void;
  delegateExists?: (attachmentId: string) => boolean;
  /** The name of the agent another attachment binds, from the live list. */
  agentNameOf?: (attachmentId: string) => string | null;
}> = ({ part, planNodeState, onSolvePlanNode, onRunPlanNode, onOpenAgentChat, delegateExists, agentNameOf }) => (
  <ul className={styles.planNodes} aria-label="Planned nodes">
    {part.plan!.nodes.map((node) => {
      const row = planNodeRowState(part, node, planNodeState);
      const linkable = Boolean(
        row.changeHomeId && onOpenAgentChat && (delegateExists ? delegateExists(row.changeHomeId) : true),
      );
      return (
        <PlanNodeRow
          key={node.ref}
          node={node}
          applied={row.applied}
          deps={row.deps}
          state={row.state}
          solvable={row.solvable}
          solveBlocker={row.solveBlocker}
          extras={planNodeExtras(part, node)}
          onSolve={onSolvePlanNode ? () => onSolvePlanNode(node.ref) : undefined}
          onRun={onRunPlanNode ? () => onRunPlanNode(node.ref) : undefined}
          onOpenChange={linkable ? () => onOpenAgentChat!(row.changeHomeId!) : undefined}
          changeAgentName={row.changeHomeId ? agentNameOf?.(row.changeHomeId) ?? undefined : undefined}
        />
      );
    })}
  </ul>
);
