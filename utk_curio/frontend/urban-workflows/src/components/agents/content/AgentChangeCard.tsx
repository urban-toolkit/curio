import React, { useState } from "react";
import type { AgentChangePart } from "../../../services/agents";
import styles from "./AgentReviewCard.module.css";
import { PlanEdgesList } from "./reviewCard/PlanEdgesList";
import { PlanNodesList } from "./reviewCard/PlanNodesList";
import { PlanScenariosList } from "./reviewCard/PlanScenariosList";
import { PlanSummary } from "./reviewCard/PlanSummary";
import { SourceBlock } from "./reviewCard/SourceBlock";
import { ValidationBlock } from "./reviewCard/ValidationBlock";
import type { PlanNodeReviewState } from "./reviewCard/reviewCardText";

/** What each kind of change is, on its card's header. */
export const CHANGE_KIND_LABEL: Record<string, string> = {
  content: "code",
  settings: "settings",
  node: "new node",
  plan: "plan",
};

/**
 * The card of a change an agent made to the dataflow (`proposals/changes.py`):
 * it landed at once, for everyone, as a person's edit does, so the card says
 * what it did and offers its Undo, a person's own change. Undo puts back what
 * the change replaced, by kind: a node's code gets its code before, a new node
 * goes with its connections, settings get their old values, a plan puts back
 * the dataflow before it. When someone changed it after, Undo is refused and
 * the card says who; nothing was undone. The code is model output: it renders
 * as inert plain text (REQ-SEC-002), never markup.
 *
 * A plan's card lists its nodes, each with Solve then Run as its code is
 * written and checked (Build & validate fills them in order), its
 * connections, its removals by name and its scenarios.
 */
export const AgentChangeCard: React.FC<{
  part: AgentChangePart;
  /** Tint class carrying the agent's category color for the accent dot. */
  tintClassName?: string;
  /** Undo the change; omitted, the card offers none. */
  onUndo?: (changeId: string) => Promise<unknown>;
  /** A plan's rows: the attachment's ledger of the plan this card is. */
  planNodeState?: PlanNodeReviewState;
  onSolvePlanNode?: (ref: string) => Promise<void>;
  onRunPlanNode?: (ref: string) => Promise<void>;
  onOpenAgentChat?: (attachmentId: string) => void;
  delegateExists?: (attachmentId: string) => boolean;
  agentNameOf?: (attachmentId: string) => string | null;
}> = ({
  part,
  tintClassName,
  onUndo,
  planNodeState,
  onSolvePlanNode,
  onRunPlanNode,
  onOpenAgentChat,
  delegateExists,
  agentNameOf,
}) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const undo = async () => {
    if (!onUndo || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onUndo(part.changeId);
    } catch (e) {
      // Refused: the server says who changed it after; nothing was undone.
      setError(e instanceof Error ? e.message : "Undo failed; nothing was undone.");
    } finally {
      setBusy(false);
    }
  };

  const isPlan = part.kind === "plan" && Boolean(part.plan);
  const undone = part.status === "undone";
  return (
    <div className={styles.card} role="group" aria-label={`Change: ${part.summary}`} data-change-status={part.status}>
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span>{part.summary}</span>
        <span className={styles.kind}>{CHANGE_KIND_LABEL[part.kind] ?? part.kind}</span>
      </div>
      {part.source ? <SourceBlock source={part.source} /> : null}
      {isPlan ? <PlanSummary part={part} /> : null}
      {(part.lines ?? []).map((line, i) => (
        <div key={`line-${i}`} className={styles.meta}>
          {line}
        </div>
      ))}
      {part.validation ? <ValidationBlock validation={part.validation} /> : null}
      {isPlan ? (
        <>
          {!undone ? (
            <PlanNodesList
              part={part}
              planNodeState={planNodeState}
              onSolvePlanNode={planNodeState ? onSolvePlanNode : undefined}
              onRunPlanNode={planNodeState ? onRunPlanNode : undefined}
              onOpenAgentChat={onOpenAgentChat}
              delegateExists={delegateExists}
              agentNameOf={agentNameOf}
            />
          ) : null}
          {part.plan?.edges?.length ? <PlanEdgesList part={part} /> : null}
          <PlanScenariosList part={part} planNodeState={planNodeState} />
        </>
      ) : part.kind === "content" || part.kind === "node" ? (
        part.preview ? <div className={styles.preview}>{part.preview}</div> : null
      ) : null}
      {undone ? (
        <div className={styles.outcome}>Undone</div>
      ) : onUndo ? (
        <div className={styles.actions}>
          <button type="button" className={styles.dismiss} disabled={busy} onClick={() => void undo()}>
            {busy ? "Undoing…" : "Undo"}
          </button>
        </div>
      ) : null}
      {error ? (
        <div className={styles.error} role="alert">
          {error}
        </div>
      ) : null}
    </div>
  );
};
