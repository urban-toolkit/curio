import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { PlanNodeRow } from "./PlanNodeRow";
import { planNodeRowState, type PlanNodeReviewState } from "./reviewCardText";

/** dev/67-5 (Simulation Mode: create): every planned node individually
 * inspectable — editable goal, expects, per-node Apply. Replaces the text
 * preview for pending plans; no generated code ever renders here (plans are
 * content-free by contract). */
export const PlanNodesList: React.FC<{
  part: AgentProposalPart;
  planNodeState?: PlanNodeReviewState;
  onApplyPlanNode: (proposalId: string, ref: string) => Promise<void>;
  onSavePlanGoal?: (proposalId: string, ref: string, goal: string) => Promise<void>;
  onSolvePlanNode?: (ref: string) => Promise<void>;
  onRunPlanNode?: (ref: string) => Promise<void>;
  onOpenAgentChat?: (attachmentId: string) => void;
  delegateExists?: (attachmentId: string) => boolean;
}> = ({ part, planNodeState, onApplyPlanNode, onSavePlanGoal, onSolvePlanNode, onRunPlanNode, onOpenAgentChat, delegateExists }) => (
  <ul className={styles.planNodes} aria-label="Planned nodes">
    {part.plan!.nodes.map((node) => {
      const row = planNodeRowState(part, node, planNodeState);
      const reviewLinkable = Boolean(
        row.reviewHomeId && onOpenAgentChat && (delegateExists ? delegateExists(row.reviewHomeId) : true),
      );
      return (
        <PlanNodeRow
          key={node.ref}
          node={node}
          applied={row.applied}
          goal={planNodeState?.editedGoals?.[node.ref] ?? node.intent}
          deps={row.deps}
          state={row.state}
          solvable={row.solvable}
          solveBlocker={row.solveBlocker}
          onApply={() => onApplyPlanNode(part.proposalId, node.ref)}
          onSaveGoal={(goal) => (onSavePlanGoal ? onSavePlanGoal(part.proposalId, node.ref, goal) : Promise.resolve())}
          onSolve={onSolvePlanNode ? () => onSolvePlanNode(node.ref) : undefined}
          onRun={onRunPlanNode ? () => onRunPlanNode(node.ref) : undefined}
          onOpenReview={reviewLinkable ? () => onOpenAgentChat!(row.reviewHomeId!) : undefined}
        />
      );
    })}
  </ul>
);
