import React, { useState } from "react";
import type { AgentProposalPart } from "../../../services/agents";
import styles from "./AgentReviewCard.module.css";
import { BackendTrustBlock } from "./reviewCard/BackendTrustBlock";
import { EffectLine } from "./reviewCard/EffectLine";
import { PackageDraftDetails } from "./reviewCard/PackageDraftDetails";
import { PlanEdgesList } from "./reviewCard/PlanEdgesList";
import { PlanNodesList } from "./reviewCard/PlanNodesList";
import { PlanSummary } from "./reviewCard/PlanSummary";
import { ReviewActions } from "./reviewCard/ReviewActions";
import { SourceBlock } from "./reviewCard/SourceBlock";
import { TemplateCreateBlocks } from "./reviewCard/TemplateCreateBlocks";
import { ValidationBlock } from "./reviewCard/ValidationBlock";
import type { PlanNodeReviewState } from "./reviewCard/reviewCardText";

// The names tests and callers reach through this module (memo dev/142, F4).
export { nodeKindExecutable } from "./reviewCard/reviewCardText";
export type { PlanNodeReviewState } from "./reviewCard/reviewCardText";

/**
 * The review-before-apply card (memo dev/41; the blueprint's planned
 * `AgentReviewCard`). The agent proposes; the USER confirms here — Apply and
 * Dismiss are system review controls (the sanctioned exception family to
 * "no agent action buttons", same as the DEC-035 install dialog). The
 * proposed content is model output: it renders as inert plain text
 * (REQ-SEC-002), never markup. Non-pending proposals render inert with
 * their outcome label.
 *
 * Since memo dev/142 (F4) the card COMPOSES one section per concern — source,
 * template-create blocks, plan summary and removals, package-draft details,
 * the backend trust edge, validation, the plan's node and connection lists,
 * the effect line, the actions — and keeps only what spans them: the busy /
 * error state of an action, and which section a proposal kind shows.
 */
export const AgentReviewCard: React.FC<{
  part: AgentProposalPart;
  /** Tint class carrying the agent's category color for the accent dot. */
  tintClassName?: string;
  /** The card awaits settlement only; a caller may resolve with its apply
   * result (dev/105 A3: the install review reads `followUpProposals`). */
  onApply?: (proposalId: string) => Promise<unknown>;
  onDismiss?: (proposalId: string) => Promise<void>;
  /** dev/67-5 (plan proposals): the per-node review state from the
   * activeProposal mirror; enables the per-node rows when present. */
  planNodeState?: PlanNodeReviewState;
  onApplyPlanNode?: (proposalId: string, ref: string) => Promise<void>;
  onSavePlanGoal?: (proposalId: string, ref: string, goal: string) => Promise<void>;
  /** dev/67-8: apply plan edges (a subset by index, or all pending). */
  onApplyPlanEdges?: (proposalId: string, indices?: number[]) => Promise<void>;
  /** dev/71: per-row Solve (the 67-7 validate loop) and Run (through node). */
  onSolvePlanNode?: (ref: string) => Promise<void>;
  onRunPlanNode?: (ref: string) => Promise<void>;
  /** dev/72: the icon-link route to a homed content review's chat. */
  onOpenAgentChat?: (attachmentId: string) => void;
  delegateExists?: (attachmentId: string) => boolean;
}> = ({ part, tintClassName, onApply, onDismiss, planNodeState, onApplyPlanNode, onSavePlanGoal, onApplyPlanEdges, onSolvePlanNode, onRunPlanNode, onOpenAgentChat, delegateExists }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [edgeBusy, setEdgeBusy] = useState<string | null>(null);

  const applyEdges = async (indices?: number[]) => {
    if (!onApplyPlanEdges || edgeBusy) return;
    setEdgeBusy(indices ? String(indices[0]) : "all");
    setError(null);
    try {
      await onApplyPlanEdges(part.proposalId, indices);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connecting failed");
    } finally {
      setEdgeBusy(null);
    }
  };

  const act = async (fn?: (proposalId: string) => Promise<unknown>) => {
    if (!fn || busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn(part.proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The review action failed");
    } finally {
      setBusy(false);
    }
  };

  const pending = part.status === "pending";
  const isPlan = part.tool === "dataflow.plan.write" && Boolean(part.plan);
  return (
    <div className={styles.card} role="group" aria-label={`Review proposal: ${part.summary}`}>
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span>{part.summary}</span>
        <span className={styles.kind}>review</span>
      </div>
      {part.source ? <SourceBlock source={part.source} /> : null}
      <TemplateCreateBlocks part={part} />
      <PlanSummary part={part} />
      {part.tool === "package.draft.apply" && part.draft ? <PackageDraftDetails draft={part.draft} /> : null}
      {part.tool === "package.draft.apply" && part.backend ? <BackendTrustBlock backend={part.backend} /> : null}
      {part.validation ? <ValidationBlock validation={part.validation} /> : null}
      {isPlan && pending && onApplyPlanNode ? (
        <PlanNodesList
          part={part}
          planNodeState={planNodeState}
          onApplyPlanNode={onApplyPlanNode}
          onSavePlanGoal={onSavePlanGoal}
          onSolvePlanNode={onSolvePlanNode}
          onRunPlanNode={onRunPlanNode}
          onOpenAgentChat={onOpenAgentChat}
          delegateExists={delegateExists}
        />
      ) : (
        <div className={styles.preview}>{part.preview}</div>
      )}
      {isPlan && part.plan?.edges?.length && pending && onApplyPlanEdges ? (
        <PlanEdgesList part={part} planNodeState={planNodeState} edgeBusy={edgeBusy} onApplyEdges={applyEdges} />
      ) : null}
      <EffectLine part={part} />
      <ReviewActions
        part={part}
        busy={busy}
        onApply={onApply ? () => void act(onApply) : undefined}
        onDismiss={onDismiss ? () => void act(onDismiss) : undefined}
      />
      {error ? <div className={styles.error}>{error}</div> : null}
    </div>
  );
};
