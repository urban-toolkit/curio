import React, { useEffect, useRef, useState } from "react";
import styles from "./AgentBuilderStrip.module.css";
import type { AgentRemedy } from "../../../services/agents";
import { AddKeyAction } from "../../connectionKeys/AddKeyAction";
import actionStyles from "../../connectionKeys/AddKeyAction.module.css";
import { OpenDatasetFinderAction } from "./OpenDatasetFinderAction";
import { stoppedByPhrase } from "../content/AgentSolveAttemptsCard";

/** What Solve this node does, on its tooltip. */
export const SOLVE_NODE_HINT =
  "Runs this node's code in the sandbox, fixes errors, and re-runs: only code that passed lands.";

/** What a running Solve this node does once the panel closes, on its tooltip. */
export const SOLVE_NODE_RUNNING_HINT = "Solve keeps running if you close this panel.";

/** What a node's source waits on, once a Solve ended waiting for it: the
 * user's pick, a download into the Data Catalog, or an install. */
type SourceWait = "pick" | "download" | "install";

/**
 * dev/115 (DEC-073, Amendment A2): Solve this node, one line under the Goal
 * line of a node-attached agent's chat: the button, then its narration while
 * it runs or how it ended, and the fix an outcome comes with. What it does is
 * the button's tooltip. The user's explicit ask is what runs the node's code
 * in the sandbox, fixes what fails, and re-runs it; the result lands as an
 * already-executed content review (or is written into an empty node).
 * Detached on the server: closing the panel does not stop it. While a build
 * runs on the node's plan it waits (*blocker* says why): it would build the
 * node beside the build, and so does a row's Solve of it. A Solve that ends
 * waiting for the node's source says what the source waits on (the done
 * payload's `sourceWait`): the user's pick, on the card this chat holds
 * because its Solve asked for it (*onShowCard*) or in its Finder's chat, a
 * download into the Data Catalog, or an install. Only a pick is asked for.
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
  /** Why the Solve may not start now: a build runs on the node's plan, or its
   * plan's row Solves it. */
  blocker?: string | null;
  /** Brings the card of the node's candidates in this chat into view; null
   * when this chat holds none. */
  onShowCard?: (() => void) | null;
}> = ({ onSolveNode, activity = null, live = false, onOpenChat, agentNameOf, blocker = null, onShowCard = null }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // What the node's source waits on, once a Solve ended waiting for it.
  const [awaitingSource, setAwaitingSource] = useState<SourceWait | null>(null);
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
    setAwaitingSource(null);
    setRemedy(null);
  }, [live, busy]);

  const solve = async () => {
    if (running || blocker) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    setAwaitingSource(null);
    setRemedy(null);
    try {
      const done = (await onSolveNode()) as
        | {
            verdict?: string;
            rounds?: number;
            unchanged?: boolean;
            written?: boolean;
            proposalId?: string;
            remedy?: AgentRemedy;
            stoppedBy?: string;
            sourceWait?: string;
          }
        | undefined;
      if (done?.remedy) setRemedy(done.remedy);
      if (done?.verdict === "pass" && done.unchanged) setNotice("Verified: the node's code ran successfully; no change needed.");
      else if (done?.verdict === "pass" && done.written) setNotice("Solved: the code ran successfully and was written to the node.");
      else if (done?.verdict === "pass") setNotice("Solved: the corrected code ran successfully; review and apply it below.");
      else if (done?.verdict === "infrastructure") setNotice("Not verified: the sandbox was unreachable; nothing was changed.");
      else if (done?.verdict === "awaiting-source") {
        // A server from before the wait was named asked for a pick.
        setAwaitingSource(done.sourceWait === "download" || done.sourceWait === "install" ? done.sourceWait : "pick");
      }
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
  // The candidates are on a card in this chat: the row points at it.
  const showCard = awaitingSource === "pick" && onShowCard ? onShowCard : null;
  const shownNotice =
    awaitingSource === "download"
      ? "Awaiting its source: it is downloading into the Data Catalog. Solve this node again once it lands."
      : awaitingSource === "install"
        ? "Awaiting its source: the dataset picked for it is not installed yet. Install it from the Data Catalog, " +
          "then Solve this node again."
        : awaitingSource === "pick"
          ? showCard
            ? "Awaiting a source: pick one on its card below with Use this source. Nothing was generated or written."
            : `Awaiting a source: ${finder ? `this node's ${finder} has` : "this node has"} candidates for you to ` +
              "pick with Use this source. Nothing was generated or written."
          : notice;

  return (
    <div className={styles.solveLine} role="group" aria-label="Solve this node">
      <button
        type="button"
        className={styles.solve}
        disabled={running || Boolean(blocker)}
        data-tooltip={running ? SOLVE_NODE_RUNNING_HINT : blocker ?? SOLVE_NODE_HINT}
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
      {showCard ? (
        <button type="button" className={actionStyles.button} onClick={showCard}>
          Show its sources
        </button>
      ) : remedy && (awaitingSource === null || awaitingSource === "pick") ? (
        <>
          <AddKeyAction remedy={remedy} />
          {/* dev/126: a data-loading node whose source is with the user. */}
          <OpenDatasetFinderAction remedy={remedy} onOpenChat={onOpenChat} agentName={finder} />
        </>
      ) : null}
    </div>
  );
};
