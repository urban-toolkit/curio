import React, { useEffect, useRef, useState } from "react";
import styles from "./AgentBuilderStrip.module.css";
import type { AgentRemedy } from "../../../services/agents";
import { AddKeyAction } from "../../connectionKeys/AddKeyAction";
import { OpenDatasetFinderAction } from "./OpenDatasetFinderAction";
import { stoppedByPhrase } from "../content/AgentSolveAttemptsCard";

/** What Solve this node does, on its tooltip. */
export const SOLVE_NODE_HINT =
  "Runs this node's code in the sandbox, fixes errors, and re-runs: only code that passed lands.";

/** What a running Solve this node does once the panel closes, on its tooltip. */
export const SOLVE_NODE_RUNNING_HINT = "Solve keeps running if you close this panel.";

/**
 * dev/115 (DEC-073, Amendment A2): Solve this node, one line under the Goal
 * line of a node-attached agent's chat: the button, then its narration while
 * it runs or how it ended, and the fix an outcome comes with. What it does is
 * the button's tooltip. The user's explicit ask is what runs the node's code
 * in the sandbox, fixes what fails, and re-runs it; the result lands as an
 * already-executed content review (or is written into an empty node).
 * Detached on the server: closing the panel does not stop it.
 */
export const NodeSolveRow: React.FC<{
  onSolveNode: () => Promise<unknown>;
  activity?: string | null;
  /** True while the server holds a running per-node Solve for this attachment. */
  live?: boolean;
  /** dev/126: open a chat by attachment id: the awaiting-selection remedy's
   * action opens the chat of the node's own agent that finds its datasets. */
  onOpenChat?: (attachmentId: string) => void;
  /** The name of the agent an attachment of this dataflow binds, from the live list. */
  agentNameOf?: (attachmentId: string) => string | null;
}> = ({ onSolveNode, activity = null, live = false, onOpenChat, agentNameOf }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [awaitingSource, setAwaitingSource] = useState(false);
  const [remedy, setRemedy] = useState<AgentRemedy | null>(null);
  const running = busy || live;

  // A Solve of this node that starts elsewhere (the plan's row for it, another
  // tab) makes the last outcome stale: it goes as that Solve starts, and the
  // running Solve's narration shows.
  const wasLive = useRef(live);
  useEffect(() => {
    const started = live && !wasLive.current;
    wasLive.current = live;
    if (!started || busy) return;
    setError(null);
    setNotice(null);
    setAwaitingSource(false);
    setRemedy(null);
  }, [live, busy]);

  const solve = async () => {
    if (running) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    setAwaitingSource(false);
    setRemedy(null);
    try {
      const done = (await onSolveNode()) as
        | { verdict?: string; rounds?: number; unchanged?: boolean; written?: boolean; proposalId?: string; remedy?: AgentRemedy; stoppedBy?: string }
        | undefined;
      if (done?.remedy) setRemedy(done.remedy);
      if (done?.verdict === "pass" && done.unchanged) setNotice("Verified: the node's code ran successfully; no change needed.");
      else if (done?.verdict === "pass" && done.written) setNotice("Solved: the code ran successfully and was written to the node.");
      else if (done?.verdict === "pass") setNotice("Solved: the corrected code ran successfully; review and apply it below.");
      else if (done?.verdict === "infrastructure") setNotice("Not verified: the sandbox was unreachable; nothing was changed.");
      else if (done?.verdict === "awaiting-source") setAwaitingSource(true);
      else if (done?.verdict === "fail")
        setNotice(
          // dev/127: the trail is a card in this chat now, with the code each
          // attempt ran — the notice says where to look and what stopped it.
          `Not fixed after ${done.rounds ?? "?"} attempt${done.rounds === 1 ? "" : "s"}${
            done.stoppedBy ? ` (${stoppedByPhrase(done.stoppedBy) || done.stoppedBy})` : ""
          }: every attempt is below with the code it ran; nothing was written.`,
        );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Solve failed");
    } finally {
      setBusy(false);
    }
  };

  // The agent that holds the candidates, the node's own that finds its
  // datasets, by its manifest's name. Read when rendering, so a list that
  // reloads after the Solve still names it.
  const finder =
    remedy?.kind === "dataset-selection" && remedy.attachmentId
      ? agentNameOf?.(remedy.attachmentId) ?? null
      : null;
  const shownNotice = awaitingSource
    ? `Awaiting a source: ${finder ? `this node's ${finder} has` : "this node has"} candidates for you to ` +
      "confirm. Nothing was generated or written."
    : notice;

  return (
    <div className={styles.solveLine} role="group" aria-label="Solve this node">
      <button
        type="button"
        className={styles.solve}
        disabled={running}
        data-tooltip={running ? SOLVE_NODE_RUNNING_HINT : SOLVE_NODE_HINT}
        onClick={() => void solve()}
      >
        {running ? "Solving…" : "Solve this node"}
      </button>
      {/* A running Solve's narration wins over how the last one ended. */}
      {running ? (
        <span className={styles.solveStatus} aria-live="polite" data-tooltip={activity ?? undefined}>
          {activity ?? SOLVE_NODE_RUNNING_HINT}
        </span>
      ) : error ? (
        <span className={`${styles.solveStatus} ${styles.error}`} data-tooltip={error}>{error}</span>
      ) : shownNotice ? (
        <span className={styles.solveStatus} role="status" data-tooltip={shownNotice}>{shownNotice}</span>
      ) : null}
      {remedy ? (
        <>
          <AddKeyAction remedy={remedy} />
          {/* dev/126: a data-loading node whose source is with the user. */}
          <OpenDatasetFinderAction remedy={remedy} onOpenChat={onOpenChat} agentName={finder} />
        </>
      ) : null}
    </div>
  );
};
