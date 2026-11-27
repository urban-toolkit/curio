import React from "react";

import styles from "../AgentReviewCard.module.css";
import { PlanNodeRow } from "./PlanNodeRow";
import { planNodeRowState, type PlanDisplay, type PlanNodeReviewState } from "./reviewCardText";

/** The chat of a node's own agent, the one that writes its code. */
export interface NodeChat {
  attachmentId: string;
  name: string;
}

/** A landed plan's nodes, one row each: its name, which opens its node's own
 * agent's chat, its state, Solve then Run as its code is written and checked,
 * and what it does. No generated code ever renders here (plans are
 * content-free by contract). */
export const PlanNodesList: React.FC<{
  part: PlanDisplay;
  planNodeState?: PlanNodeReviewState;
  /** Each tells the row's `onLine` how far a download its run waits on has come. */
  onSolvePlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  onRunPlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  onOpenAgentChat?: (attachmentId: string) => void;
  delegateExists?: (attachmentId: string) => boolean;
  /** The name of the agent another attachment binds, from the live list. */
  agentNameOf?: (attachmentId: string) => string | null;
  /** The node's own agent that writes its code, from the live list. */
  nodeChatOf?: (nodeId: string) => NodeChat | null;
}> = ({ part, planNodeState, onSolvePlanNode, onRunPlanNode, onOpenAgentChat, delegateExists, agentNameOf, nodeChatOf }) => (
  <ul className={styles.planNodes} aria-label="Planned nodes">
    {part.plan!.nodes.map((node) => {
      const row = planNodeRowState(part, node, planNodeState);
      // The chat that holds the change its code landed as, else its node's
      // own agent's, which writes it.
      const home =
        row.changeHomeId && (delegateExists ? delegateExists(row.changeHomeId) : true)
          ? { attachmentId: row.changeHomeId, name: agentNameOf?.(row.changeHomeId) ?? null }
          : row.nodeId
            ? nodeChatOf?.(row.nodeId) ?? null
            : null;
      return (
        <PlanNodeRow
          key={node.ref}
          node={node}
          view={row.view}
          solvable={row.solvable}
          check={row.check}
          atWork={row.atWork}
          afterLabel={row.afterLabel}
          reason={row.reason}
          notice={row.notice}
          onSolve={onSolvePlanNode ? (onLine) => onSolvePlanNode(node.ref, onLine) : undefined}
          onRun={onRunPlanNode ? (onLine) => onRunPlanNode(node.ref, onLine) : undefined}
          onOpenChat={home && onOpenAgentChat ? () => onOpenAgentChat(home.attachmentId) : undefined}
          chatAgentName={home?.name ?? null}
        />
      );
    })}
  </ul>
);
