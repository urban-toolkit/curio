import React, { useId, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faChevronUp } from "@fortawesome/free-solid-svg-icons";
import type { AgentChangePart } from "../../../services/agents";
import styles from "./AgentReviewCard.module.css";
import { PlanDetails } from "./reviewCard/PlanDetails";
import { PlanNodesList, type NodeChat } from "./reviewCard/PlanNodesList";
import { PlanSummary } from "./reviewCard/PlanSummary";
import { SourceBlock } from "./reviewCard/SourceBlock";
import { ValidationBlock } from "./reviewCard/ValidationBlock";
import { nodeKindExecutable, planTitle, type PlanNodeReviewState } from "./reviewCard/reviewCardText";

/** dev/115 (Amendment A2) → dev/118 (DEC-075) → dev/119 (DEC-076): what Solve
 * does with a new node that loads data. Whether the sandbox can run its kind
 * is the ROSTER's answer (`executable`), falling back to the registry
 * descriptor; unknown says nothing rather than guessing. */
const SolveLine: React.FC<{ part: AgentChangePart }> = ({ part }) => {
  const executable = nodeKindExecutable({ nodeType: part.nodeType, executable: part.executable });
  if (executable === null) return null;
  return (
    <div className={styles.meta}>
      {executable
        ? "Solve runs it in the sandbox and fixes errors before its code is trusted."
        : "This kind has no code to run: Solve writes it, the browser or its own service renders it; it is never called verified."}
    </div>
  );
};

/** What a plan's Undo takes back, on its tooltip. */
export const PLAN_UNDO_HINT = "Takes the plan back";
export const PLAN_UNDO_GOAL_HINT = "Takes the plan back, and the goal it set";

/**
 * The card of a change an agent made to the dataflow (`proposals/changes.py`):
 * it landed at once, for everyone, as a person's edit does, so the card says
 * what it did and offers its Undo, a person's own change. Undo puts back what
 * the change replaced, by kind: a node's code gets its code before, a new node
 * goes with its connections, settings get their old values, a plan puts back
 * the dataflow before it. When someone changed it after, Undo is refused and
 * the card says who; nothing was undone. The chat keeps that reason for the
 * card (`refusal`), so the card says it though a read of the chat draws it
 * anew, until the user acts on it again. Either says it only while the card
 * holds the status it was refused on: undone by someone else since, it has
 * nothing to say. The code is model output: it renders as inert plain text
 * (REQ-SEC-002), never markup. Its title says what it is: no chip names its
 * kind.
 *
 * A plan's card, "Plan: 3 nodes, 2 connections", lists its nodes, one row
 * each with its state, its Solve while it can run and its Run once built
 * (Build & validate fills them in order); what it removed, and what it left
 * undone or did not save. Its Details hold the goal it set, its checks, each
 * node's kind and what it reads and writes, its connections and its
 * scenarios.
 */
export const AgentChangeCard: React.FC<{
  part: AgentChangePart;
  /** Tint class carrying the agent's category color for the accent dot. */
  tintClassName?: string;
  /** Undo the change; omitted, the card offers none. */
  onUndo?: (changeId: string) => Promise<unknown>;
  /** Why the server refused the card's last Undo, as the chat keeps it
   * until the user acts on the card again: said in place of the card's own
   * record of it, which a card drawn anew no longer holds. */
  refusal?: string | null;
  /** A plan's rows: the attachment's ledger of the plan this card is. */
  planNodeState?: PlanNodeReviewState;
  onSolvePlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  onRunPlanNode?: (ref: string, onLine?: (line: string) => void) => Promise<void>;
  onOpenAgentChat?: (attachmentId: string) => void;
  delegateExists?: (attachmentId: string) => boolean;
  agentNameOf?: (attachmentId: string) => string | null;
  /** A plan node's own agent, whose chat its row's name opens. */
  nodeChatOf?: (nodeId: string) => NodeChat | null;
}> = ({
  part,
  tintClassName,
  onUndo,
  refusal = null,
  planNodeState,
  onSolvePlanNode,
  onRunPlanNode,
  onOpenAgentChat,
  delegateExists,
  agentNameOf,
  nodeChatOf,
}) => {
  const [busy, setBusy] = useState(false);
  // Why the card's own last Undo was refused, with the status it was refused
  // on: once the card's status moves on, the reason goes.
  const [error, setError] = useState<{ why: string; on: string } | null>(null);
  const own = error && error.on === part.status ? error.why : null;
  const said = busy ? null : refusal ?? own;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();

  const undo = async () => {
    if (!onUndo || busy) return;
    const on = part.status;
    setBusy(true);
    setError(null);
    try {
      await onUndo(part.changeId);
    } catch (e) {
      // Refused: the server says who changed it after; nothing was undone.
      setError({ why: e instanceof Error ? e.message : "Undo failed; nothing was undone.", on });
    } finally {
      setBusy(false);
    }
  };

  const isPlan = part.kind === "plan" && Boolean(part.plan);
  const undone = part.status === "undone";
  const undoControl = undone ? (
    <div className={styles.outcome}>Undone</div>
  ) : onUndo ? (
    <button
      type="button"
      className={styles.dismiss}
      disabled={busy}
      data-tooltip={isPlan ? (part.goalSet ? PLAN_UNDO_GOAL_HINT : PLAN_UNDO_HINT) : undefined}
      onClick={() => void undo()}
    >
      {busy ? "Undoing…" : "Undo"}
    </button>
  ) : null;
  // The scenarios the plan could not save stay in view.
  const unsaved = isPlan
    ? (part.plan?.scenarios ?? [])
        .filter((_, index) => planNodeState?.scenarioStates?.[String(index)] === "refused")
        .map((scenario) => scenario.name)
    : [];
  return (
    <div className={styles.card} role="group" aria-label={`Change: ${part.summary}`} data-change-status={part.status}>
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span>{isPlan ? planTitle(part) : part.summary}</span>
      </div>
      {isPlan ? (
        <>
          <PlanSummary part={part} />
          {part.leftUndone ? <div className={styles.planWarning}>{part.leftUndone}</div> : null}
          {unsaved.length ? <div className={styles.planWarning}>{`Not saved ✗: ${unsaved.join(", ")}`}</div> : null}
          {!undone ? (
            <PlanNodesList
              part={part}
              planNodeState={planNodeState}
              onSolvePlanNode={planNodeState ? onSolvePlanNode : undefined}
              onRunPlanNode={planNodeState ? onRunPlanNode : undefined}
              onOpenAgentChat={onOpenAgentChat}
              delegateExists={delegateExists}
              agentNameOf={agentNameOf}
              nodeChatOf={nodeChatOf}
            />
          ) : null}
          <div className={styles.planFoot}>
            <button
              type="button"
              className={styles.planDetailsToggle}
              aria-expanded={detailsOpen}
              aria-controls={detailsOpen ? detailsId : undefined}
              onClick={() => setDetailsOpen((open) => !open)}
            >
              Details
              <FontAwesomeIcon icon={detailsOpen ? faChevronUp : faChevronDown} aria-hidden="true" />
            </button>
            <span className={styles.planNodeSpacer} />
            {undoControl}
          </div>
          {detailsOpen ? <PlanDetails id={detailsId} part={part} planNodeState={planNodeState} /> : null}
        </>
      ) : (
        <>
          {part.source ? <SourceBlock source={part.source} /> : null}
          {(part.lines ?? []).map((line, i) => (
            <div key={`line-${i}`} className={styles.meta}>
              {line}
            </div>
          ))}
          {part.validation ? <ValidationBlock validation={part.validation} /> : null}
          {part.kind === "content" || part.kind === "node" ? (
            part.preview ? <div className={styles.preview}>{part.preview}</div> : null
          ) : null}
          {part.kind === "node" && part.source ? <SolveLine part={part} /> : null}
          {undoControl ? <div className={styles.actions}>{undoControl}</div> : null}
        </>
      )}
      {said ? (
        <div className={styles.error} role="alert">
          {said}
        </div>
      ) : null}
    </div>
  );
};
