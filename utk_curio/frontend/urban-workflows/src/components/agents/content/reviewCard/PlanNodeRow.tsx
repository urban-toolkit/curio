import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";

import styles from "../AgentReviewCard.module.css";
import { ROW_STATE_CHIP } from "./reviewCardText";

/** One planned node's review row (dev/67-5 + dev/71 progressive lifecycle):
 * editable goal, dependencies by name, Apply → Solve → Run per node. */
export const PlanNodeRow: React.FC<{
  node: { ref: string; nodeType: string; title: string; intent: string; expects?: string; scenario?: string };
  applied: boolean;
  goal: string;
  /** dev/71: dependency labels + readiness. */
  deps: string[];
  state: string;
  solvable: boolean;
  solveBlocker: string | null;
  /** #662: why it cannot be created yet (a copy before the node it copies). */
  createBlocker?: string | null;
  /** #662: its scenario, the node a copy copies, its widgets. */
  extras?: string[];
  onApply: () => Promise<void>;
  onSaveGoal: (goal: string) => Promise<void>;
  onSolve?: () => Promise<void>;
  onRun?: () => Promise<void>;
  /** dev/72: opens the node agent's chat, where the content review lives. */
  onOpenReview?: () => void;
  reviewAgentName?: string;
}> = ({ node, applied, goal, deps, state, solvable, solveBlocker, createBlocker, extras, onApply, onSaveGoal, onSolve, onRun, onOpenReview, reviewAgentName }) => {
  const [draft, setDraft] = useState(goal);
  const [busy, setBusy] = useState(false);
  // #662: a copy has its original's title; its scenario tells them apart.
  const label = node.scenario ? `${node.title} (${node.scenario})` : node.title;
  const [rowBusy, setRowBusy] = useState<"solve" | "run" | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const act = async (kind: "solve" | "run", fn?: () => Promise<void>) => {
    if (!fn || rowBusy) return;
    setRowBusy(kind);
    setRowError(null);
    try {
      await fn();
    } catch (e) {
      setRowError(e instanceof Error ? e.message : `The ${kind} failed`);
    } finally {
      setRowBusy(null);
    }
  };

  const saveGoal = async () => {
    const next = draft.trim();
    if (!next || next === goal.trim()) return;
    setRowError(null);
    try {
      await onSaveGoal(next);
    } catch (e) {
      setRowError(e instanceof Error ? e.message : "The goal edit failed");
    }
  };

  const apply = async () => {
    if (busy || applied) return;
    setBusy(true);
    setRowError(null);
    try {
      await onApply();
    } catch (e) {
      setRowError(e instanceof Error ? e.message : "Creating the node failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className={styles.planNodeRow}>
      <div className={styles.planNodeHead}>
        <span className={styles.planNodeTitle}>{node.title}</span>
        <span className={styles.planNodeType}>{node.nodeType}</span>
        {!applied ? (
          <button
            type="button"
            className={styles.apply}
            disabled={busy || Boolean(createBlocker)}
            title={createBlocker ?? undefined}
            onClick={() => void apply()}
            aria-label={`Create node ${label}`}
          >
            {busy ? "Creating…" : "Apply"}
          </button>
        ) : (
          <>
            {ROW_STATE_CHIP[state] ? (
              <span
                className={
                  state === "failed" ? styles.planEdgeRefused : styles.planNodeCreated
                }
              >
                {ROW_STATE_CHIP[state]}
                {/* dev/72: the icon-link to the node agent's chat, where the
                    content review (and the Solve trace) lives. */}
                {onOpenReview ? (
                  <button
                    type="button"
                    className={styles.reviewLink}
                    aria-label={`Open ${reviewAgentName ?? "the node agent"}'s chat`}
                    title={`Open ${reviewAgentName ?? "the node agent"}'s chat`}
                    onClick={onOpenReview}
                  >
                    <FontAwesomeIcon icon={faRobot} />
                  </button>
                ) : null}
              </span>
            ) : (
              <span className={styles.planNodeCreated}>Created ✓</span>
            )}
            {onSolve && (state === "created" || state === "failed") ? (
              <button
                type="button"
                className={styles.apply}
                disabled={rowBusy !== null || !solvable}
                title={solveBlocker ?? undefined}
                onClick={() => void act("solve", onSolve)}
                aria-label={`Solve node ${label}`}
              >
                {rowBusy === "solve" ? "Solving…" : "Solve"}
              </button>
            ) : null}
            {onRun && state === "approved" ? (
              <button
                type="button"
                className={styles.run}
                disabled={rowBusy !== null}
                onClick={() => void act("run", onRun)}
                aria-label={`Run through node ${label}`}
              >
                {rowBusy === "run" ? "Running…" : "Run"}
              </button>
            ) : null}
          </>
        )}
      </div>
      {deps.length ? (
        <div className={styles.planNodeExpects}>needs: {deps.join(", ")}</div>
      ) : null}
      {node.expects ? <div className={styles.planNodeExpects}>{node.expects}</div> : null}
      {(extras ?? []).map((line) => (
        <div key={line} className={styles.planNodeExpects}>
          {line}
        </div>
      ))}
      <textarea
        className={styles.planGoalInput}
        value={draft}
        disabled={applied}
        rows={2}
        aria-label={`Goal for ${label}`}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void saveGoal()}
      />
      {rowError ? <div className={styles.error}>{rowError}</div> : null}
    </li>
  );
};
