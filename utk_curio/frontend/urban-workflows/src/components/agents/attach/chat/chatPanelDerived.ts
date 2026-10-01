/**
 * Pure derivations the chat panel renders from (memo dev/142, F4 — split out
 * of `AgentChatPanel.tsx`): the per-turn status meta, the plan-row state a
 * review card gets from the attachment's mirrors, the header's target label,
 * and the newest turn's suggested prompts.
 */
import {
  turnStatusDisplay,
  type AgentAttachment,
  type AgentProposalPart,
  type AgentSessionTurn,
  type AgentSuggestedPromptsPart,
  type AgentRunStatus,
  type RunStatusDisplay,
} from "../../../../services/agents";
import type { PlanNodeReviewState } from "../../content/AgentReviewCard";

/** Heuristic: prompts longer than this get the clamp + expand toggle. */
export const INTENT_CLAMP_CHARS = 280;

/** The meta line under one agent turn: the streaming reply shows the live
 * running indicator; finalized replies show their persisted execution
 * record; the newest reply falls back to the live run record when an old
 * server sent no execution fields — so a final message never renders bare. */
export function turnMetaFor(
  t: AgentSessionTurn,
  i: number,
  ctx: {
    turns: AgentSessionTurn[];
    runStatus: AgentRunStatus | null | undefined;
    runInFlight: boolean;
    lastAgentIdx: number;
    pendingReview: boolean;
  },
): RunStatusDisplay | null {
  const { turns, runStatus, runInFlight, lastAgentIdx, pendingReview } = ctx;
  const isLast = i === turns.length - 1;
  if (runInFlight && isLast && t.role === "agent" && !t.error && runStatus)
    return { kind: "running", startedAt: runStatus.startedAt };
  const derived = turnStatusDisplay(t, { pendingReview: i === lastAgentIdx && pendingReview });
  if (derived) {
    // The just-failed reply's elapsed-at-failure lives on the run record
    // (client error turns carry no execution).
    if (derived.kind === "error" && derived.durationMs == null && isLast && runStatus?.phase === "error")
      return { ...derived, durationMs: runStatus.durationMs };
    return derived;
  }
  if (isLast && t.role === "agent" && !t.error && runStatus?.phase === "done")
    return {
      kind: "done",
      durationMs: runStatus.durationMs,
      usage: runStatus.usage ?? null,
      pendingReview: i === lastAgentIdx && pendingReview,
    };
  return null;
}

/** dev/67-5/67-9: the mirror's per-node state feeds the part whose proposal
 * it mirrors — active OR parked behind a content review. */
export function planNodeStateFor(
  attachment: AgentAttachment,
  part: AgentProposalPart,
): PlanNodeReviewState | undefined {
  const mirror =
    attachment.activeProposal?.proposalId === part.proposalId
      ? attachment.activeProposal
      : attachment.planProposal?.proposalId === part.proposalId
        ? attachment.planProposal
        : null;
  return mirror
    ? {
        appliedRefs: mirror.appliedRefs ?? [],
        editedGoals: mirror.editedGoals ?? {},
        edgeStates: mirror.edgeStates ?? {},
        nodeStates: attachment.builderSession?.nodeStates ?? {}, // dev/71: the lifecycle ledger
        nodeProposals: attachment.builderSession?.nodeProposals ?? {}, // dev/72: where each review lives
      }
    : undefined;
}

/** "Attached to <name>", not "Attached to node 6bea6863-…" (#228). The name
 * is resolved by the overlay, which can see the canvas; falls back to the old
 * shape when the node is gone. */
export function targetLabelFor(attachment: AgentAttachment, targetName: string | null): string {
  return attachment.target.kind === "canvas"
    ? "canvas"
    : targetName?.trim() || `${attachment.target.kind} ${attachment.target.targetId ?? ""}`.trim();
}

/** The diagnostic ids live in the subtitle's tooltip rather than the header (#228). */
export function targetTooltipFor(attachment: AgentAttachment): string {
  return attachment.target.kind === "canvas"
    ? `session ${attachment.sessionId}`
    : `${attachment.target.kind} ${attachment.target.targetId ?? ""} · session ${attachment.sessionId}`;
}

/** SUGGESTED PROMPTS (memo dev/39, docs/08): only the newest turn's part
 * counts — once the user replies, earlier follow-ups are stale noise. */
export function suggestedPromptsOf(turns: AgentSessionTurn[]): AgentSuggestedPromptsPart | null {
  const last = turns[turns.length - 1];
  if (!last || last.role !== "agent" || last.error) return null;
  const part = (last.content ?? []).find((p) => p.type === "suggestedPrompts");
  return (part as AgentSuggestedPromptsPart | undefined) ?? null;
}
