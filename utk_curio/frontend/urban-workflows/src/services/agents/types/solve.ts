/**
 * Solve: waves, per-node results, the batch result, and the attempt-trail transcript part.
 *
 * Split out of `api/agentsApi.ts` (memo dev/142, F1); every shape keeps its name.
 */

import type { AgentRemedy, AgentValidationAttempt } from "./evidence";
import type { AgentBuilderSession } from "./proposal";

/** dev/118 (DEC-075): one topological wave of a Solve batch, from `solve_wave`. */
export interface AgentSolveWave {
  wave: number;
  of: number;
  nodeIds: string[];
}

/** One node's outcome on the Solve payload (dev/63; dev/115 adds the verdict). */
export interface AgentSolveNodeResult {
  status: "solved" | "failed" | "skipped" | "pending" | "proposed" | string;
  error?: string;
  /** dev/115: a sandbox outage leaves the node pending with this reason. */
  reason?: string;
  verdict?: "pass" | "fail" | "infrastructure" | string;
  rounds?: number;
  attempts?: AgentValidationAttempt[];
  proposalId?: string;
  proposalAttachmentId?: string | null;
  /** dev/116: present when the failure asks for a connection key. */
  remedy?: AgentRemedy;
  /** dev/127: which bound ended the repair loop (rounds, budget, repeat, …). */
  stoppedBy?: string;
  /** dev/118: a browser-rendered kind was written, not executed. `reason`
   * above also carries the batch's time budget or a slice bound (pending/skipped). */
  verification?: { status: "not-executable" | string; reason?: string };
}

export interface AgentSolveResult {
  attachmentId: string;
  executionId: string;
  results: Record<string, AgentSolveNodeResult>;
  appliedContents: Array<{ nodeId: string; content: string }>;
  builderSession: AgentBuilderSession;
  /** dev/63: true when the batch was cancelled (endpoint or disconnect). */
  cancelled?: boolean;
  /** dev/63: targets never dispatched — reverted to pending. */
  notAttempted?: string[];
  /** dev/106: the batch-level failure reason (the missing-specialist case) —
   * the same text every node's `error` carries; the Solve card shows it once. */
  reason?: string;
  /** dev/131: how the SESSION ended — complete | stopped | budget | blocked. */
  endedBy?: string;
  /** dev/131: how many passes the session made. */
  passes?: number;
  /** dev/131: what it is still blocked on, per node. */
  waiting?: Array<{
    nodeId: string;
    kind: string;
    reason?: string;
    attachmentId?: string | null;
  }>;
}

/** dev/127: one attempt a repair loop made — the code it ran beside the error
 *  it produced. Runtime-minted only; a model can never author one. */
export interface AgentSolveAttemptRow {
  round: number;
  verdict: string;
  kind: string;
  /** The error, read for its exception line (which leads and stays whole). */
  error: string;
  errorTruncated?: boolean;
  /** The candidate this round ran. Absent for a round that passed. */
  code?: string;
  codeTruncated?: boolean;
  /** dev/115: the builder's decline is prose — never rendered as runnable code. */
  codeIsProse?: boolean;
  durationMs?: number;
  outputDataType?: string;
  contentSha256?: string;
  source?: string;
}

/** dev/127: every attempt to fix ONE node, in the transcript, durably. */
export interface AgentSolveAttemptsPart {
  type: "solveAttempts";
  nodeId: string;
  label: string;
  /** The node's own agent — the chat where the child's replies live. */
  attachmentId?: string | null;
  rounds: number;
  /** Which bound ended the loop: rounds, budget, repeat, decline, … */
  stoppedBy: string;
  verdict: string;
  attempts: AgentSolveAttemptRow[];
  /** Attempts beyond the part's cap, if any. */
  elided?: number;
}
