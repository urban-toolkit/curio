import React, { useState } from "react";
import styles from "./AgentBuilderStrip.module.css";
import type { AgentRemedy } from "../../../api/agentsApi";
import { AddKeyAction } from "../../connectionKeys/AddKeyAction";

/**
 * dev/115 (DEC-073, Amendment A2): the per-node Solve row — rendered in a
 * node-attached agent's chat. The user's explicit ask is what runs the node's
 * code in the sandbox, fixes what fails, and re-runs it; the result lands as
 * an already-executed content review (or is written into an empty node).
 * Detached on the server: closing the panel does not stop it.
 */
export const NodeSolveRow: React.FC<{
  onSolveNode: () => Promise<unknown>;
  activity?: string | null;
  /** True while the server holds a running per-node Solve for this attachment. */
  live?: boolean;
}> = ({ onSolveNode, activity = null, live = false }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [remedy, setRemedy] = useState<AgentRemedy | null>(null);
  const running = busy || live;

  const solve = async () => {
    if (running) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    setRemedy(null);
    try {
      const done = (await onSolveNode()) as
        | { verdict?: string; rounds?: number; unchanged?: boolean; written?: boolean; proposalId?: string; remedy?: AgentRemedy }
        | undefined;
      if (done?.remedy) setRemedy(done.remedy);
      if (done?.verdict === "pass" && done.unchanged) setNotice("Verified — the node's code ran successfully; no change needed.");
      else if (done?.verdict === "pass" && done.written) setNotice("Solved — the code ran successfully and was written to the node.");
      else if (done?.verdict === "pass") setNotice("Solved — the corrected code ran successfully; review and apply it below.");
      else if (done?.verdict === "infrastructure") setNotice("Not verified — the sandbox was unreachable; nothing was changed.");
      else if (done?.verdict === "fail")
        setNotice(`Not fixed after ${done.rounds ?? "?"} attempts — the trail is in the transcript; nothing was written.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Solve failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.strip} role="group" aria-label="Solve this node">
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.solve}
          disabled={running}
          title="Runs the node's current code in the sandbox, fixes errors, re-runs, and lands only code that passed"
          onClick={() => void solve()}
        >
          {running ? "Solving…" : "Solve this node"}
        </button>
        <span className={styles.hint}>
          {running
            ? "Solve keeps running if you close this panel."
            : "Runs the code in the sandbox, fixes errors, re-runs — only code that passed lands."}
        </span>
      </div>
      {running && activity ? (
        <div className={styles.hint} aria-live="polite">{activity}</div>
      ) : null}
      {notice ? <div className={styles.hint} role="status">{notice}</div> : null}
      {remedy ? (
        <div className={styles.actions}>
          <AddKeyAction remedy={remedy} />
        </div>
      ) : null}
      {error ? <div className={styles.error}>{error}</div> : null}
    </div>
  );
};
