/**
 * The builder strip's pure vocabulary and derivations (memo dev/142, F4 —
 * split out of `AgentBuilderStrip.tsx`; every name kept): the phase chips and
 * their rank, what a live pill state means in words, how a session's ending
 * reads, why Solve is disabled, and the two remedy de-duplications.
 */
import type { AgentRemedy, AgentSolveWave } from "../../../../services/agents";

export const PHASES: Array<{ id: string; label: string }> = [
  { id: "idle", label: "Plan" },
  { id: "plan_review", label: "Review" },
  { id: "applied", label: "Solve" },
  { id: "ready", label: "Ready" },
];

export const PHASE_RANK: Record<string, number> = {
  idle: 0,
  plan_review: 1,
  simulating: 2, // dev/67-5: per-node create/solve in progress
  applied: 2,
  solving: 2,
  interrupted: 2, // dev/115: the server stopped mid-solve — Retry continues
  ready: 3,
};

/** dev/115: what a live pill state means, in words (never colour alone). */
export const STATUS_LABEL: Record<string, string> = {
  solving: "solving",
  generating: "generating…",
  verifying: "verifying — running in the sandbox…",
  fixing: "fixing — the run failed, correcting…",
  verified: "solved ✓ verified",
  written: "written — no code to run; renders in the browser or its own service",
  solved: "solved",
  failed: "failed",
  skipped: "skipped",
  pending: "pending",
  proposed: "review pending",
};

export type SolveWaitingRow = { nodeId: string; kind: string; reason?: string; attachmentId?: string | null };

const TERMINAL = new Set(["solved", "verified", "written", "failed", "skipped"]);

/** The running-status line's detail: the wave in words when the batch runs
 * in waves (dev/118), and the fraction of terminal node states. */
export function batchDetailFor(entries: Array<[string, string]>, solveWave: AgentSolveWave | undefined): string | undefined {
  const batchDone = entries.filter(([, s]) => TERMINAL.has(s)).length;
  const nodesDetail = entries.length > 0 ? `${batchDone}/${entries.length} nodes` : undefined;
  const waveDetail =
    solveWave && solveWave.of > 1
      ? `wave ${solveWave.wave} of ${solveWave.of} — ${solveWave.nodeIds.length} node${solveWave.nodeIds.length === 1 ? "" : "s"}`
      : null;
  return [waveDetail, nodesDetail].filter(Boolean).join(" · ") || undefined;
}

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** dev/131: how the last session ended, as the strip's one honest line. */
export function sessionEndingText(endedBy: string, unresolved: number): string {
  const pending = unresolved ? ` — ${plural(unresolved, "node")} still pending.` : ".";
  return endedBy === "complete"
    ? "Finished — nothing left to do."
    : endedBy === "stopped"
      ? `Stopped by you${pending}`
      : endedBy === "budget"
        ? `Out of time for this session${pending}`
        : endedBy === "blocked"
          ? "Stopped — a specialist must be installed first."
          : "";
}

/** dev/131: the pass line while the session runs. */
export function passLineText(pass: number, unresolved: number, userBlocked: number): string {
  return (
    `Managing the dataflow — pass ${pass}` +
    (unresolved ? ` · ${plural(unresolved, "node")} left` : "") +
    (userBlocked ? ` · waiting for you on ${plural(userBlocked, "node")}` : "")
  );
}

/** Why the Solve button is disabled, or null when it is not. dev/131: a node
 * waiting for the USER (a dataset selection) cannot be helped by pressing
 * Solve — "while depending on user's input, the solve button should be
 * deactivated". */
export function solveDisabledReasonFor(opts: {
  phase: string;
  unresolved: number;
  everyUnresolvedNeedsUser: boolean;
  userBlockedCount: number;
}): string | null {
  const { phase, unresolved, everyUnresolvedNeedsUser, userBlockedCount } = opts;
  return phase === "plan_review"
    ? "Apply or dismiss the plan review first"
    : phase === "idle"
      ? "Apply a plan first"
      : unresolved === 0
        ? "No pending nodes"
        : everyUnresolvedNeedsUser
          ? `Waiting for you: ${
              userBlockedCount === 1 ? "confirm a dataset source" : `confirm a dataset source for ${userBlockedCount} nodes`
            }`
          : null;
}

/** dev/116: one action per host, whatever the number of nodes that need it. */
export function remediesByHost(solveRemedies: Record<string, AgentRemedy> | undefined): AgentRemedy[] {
  return Object.values(solveRemedies ?? {}).filter(
    (r, i, all) => r && r.host && all.findIndex((o) => o.kind === r.kind && o.host === r.host) === i,
  );
}

/** dev/126: one button per node awaiting a selection (two nodes never share
 * a Dataset Finder attachment). */
export function selectionRemediesOf(solveRemedies: Record<string, AgentRemedy> | undefined): Array<[string, AgentRemedy]> {
  return Object.entries(solveRemedies ?? {}).filter(([, r]) => r?.kind === "dataset-selection" && r.attachmentId);
}

/** One line per DISTINCT text (six identical node failures → one line). */
export function distinctLines(byNode: Record<string, string> | undefined): string[] {
  return Array.from(new Set(Object.values(byNode ?? {}).filter(Boolean)));
}
