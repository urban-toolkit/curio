import type { AgentSessionTurn, AgentUsage } from "../../../api/agentsApi";

/**
 * Live per-attachment run state (memo dev/80), owned by
 * AgentAttachmentsProvider — the source of truth for the chat status strip.
 * A `running` entry appears when a send starts; the SAME synchronous block
 * that lands the final turn finalizes it to `done`/`error`, so the final
 * assistant message is never visible without an accompanying status.
 */
export interface AgentRunStatus {
  phase: "running" | "done" | "error";
  /** Epoch ms when the send started — drives the elapsed ticker. */
  startedAt: number;
  /** Authoritative from the done payload when present, else client-measured. */
  durationMs?: number;
  /** The finished run's Actual usage (memo dev/37) — null when unreported. */
  usage?: AgentUsage | null;
  /** Interim provider-reported sums from the stream's `usage` events —
   * meaningful only while `phase === "running"`. */
  liveUsage?: AgentUsage | null;
}

/** Rotating processing labels for the live indicator. The index derives from
 * elapsed seconds (see useRunTicker) — deterministic, never random. */
export const PROCESSING_LABELS = [
  "Cooking",
  "Baking",
  "Simmering",
  "Brewing",
  "Whisking",
  "Plating",
] as const;

/** Seconds each processing label stays before rotating to the next. */
export const LABEL_ROTATE_SECONDS = 5;

/** Live elapsed readout: `0:07`, `1:23`, `61:05` (minutes unbounded). */
export function formatElapsed(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Finished-run duration: `12s` under a minute, `1m 23s` beyond. */
export function formatDuration(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  if (totalSec < 60) return `${totalSec}s`;
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

/** Compact token figure: `999`, `1.0k`, `12.3k`, `1.2M`. */
export function formatTokenCount(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/**
 * Cumulative provider-reported session usage: the sum of every turn's
 * persisted execution usage (memo dev/37) plus the in-flight run's interim
 * sums when given. Returns null when nothing was ever reported — the counter
 * shows nothing rather than a fabricated 0 (dev/11/37: Actuals only).
 */
export function sessionTokenTotals(
  turns: AgentSessionTurn[],
  liveUsage?: AgentUsage | null,
): AgentUsage | null {
  let inputTokens = 0;
  let outputTokens = 0;
  let seen = false;
  for (const t of turns) {
    const u = t.execution?.usage;
    if (!u) continue;
    seen = true;
    inputTokens += u.inputTokens ?? 0;
    outputTokens += u.outputTokens ?? 0;
  }
  if (liveUsage) {
    seen = true;
    inputTokens += liveUsage.inputTokens ?? 0;
    outputTokens += liveUsage.outputTokens ?? 0;
  }
  return seen ? { inputTokens, outputTokens } : null;
}

/** What the status line renders — live phases plus the rehydrated fallback. */
export type RunStatusDisplay =
  | { kind: "running"; startedAt: number }
  | {
      kind: "done";
      durationMs?: number;
      usage?: AgentUsage | null;
      /** A review proposal awaits the user (derived from the attachment's
       * proposal mirrors — self-clearing on apply/dismiss). */
      pendingReview?: boolean;
    }
  | { kind: "error"; durationMs?: number };

/**
 * ONE agent turn's execution status (dev/80 amendment: the status is
 * per-reply, not transcript-global). An error marker derives the failed
 * state; a persisted execution record (dev/37) derives the finished state
 * with that run's duration and tokens. Pre-dev/37 turns without a record
 * yield null rather than a fabricated status; user turns never have one.
 */
export function turnStatusDisplay(
  turn: AgentSessionTurn,
  opts?: { pendingReview?: boolean },
): RunStatusDisplay | null {
  if (turn.role !== "agent") return null;
  if (turn.error) return { kind: "error", durationMs: turn.execution?.durationMs };
  if (!turn.execution) return null;
  return {
    kind: "done",
    durationMs: turn.execution.durationMs,
    usage: turn.execution.usage ?? null,
    pendingReview: opts?.pendingReview,
  };
}
