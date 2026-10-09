/**
 * A transcript: usage and execution records, the typed content parts a turn may carry, turns, and the session.
 *
 * Split out of `api/agentsApi.ts` (memo dev/142, F1); every shape keeps its name.
 */

import type { AgentDatasetCandidateRow, AgentRemedy } from "./evidence";
import type { AgentDataflowPlanPart, AgentProposalPart } from "./proposal";
import type { AgentSolveAttemptsPart } from "./solve";

/** Actual provider-reported token usage (memo dev/37) — never an estimate. */
export interface AgentUsage {
  inputTokens: number;
  outputTokens: number;
}

/**
 * One tool call of a run (memo dev/41): the tool, how it ended, and, for a
 * call that did not succeed, the one-line reason the chat shows under the
 * reply (#447). Saved turns from before the reason have none.
 */
export interface AgentToolCall {
  tool: string;
  status: string;
  durationMs?: number;
  reason?: string;
}

/**
 * The per-run execution record riding an agent turn (memo dev/37): identity,
 * DEC-031 reproducibility pins, duration, status, and Actual usage (null when
 * the provider reports none). Turns that predate the record simply lack it.
 */
export interface AgentExecution {
  executionId: string;
  /** Present on a delegated task's record: the run that delegated it (dev/48). */
  parentExecutionId?: string | null;
  pins?: {
    coord?: string;
    promptSha256?: string | null;
    intentEdited?: boolean;
    provider?: string;
    model?: string;
    /** The LLM configuration that answered: never its key. */
    llm?: { configId: string | null; label: string; baseUrlHost: string; source: string };
    policy?: Record<string, number | null>;
  };
  usage: AgentUsage | null;
  durationMs?: number;
  status: "ok" | "error";
  /** The tool calls the run made, in order; absent when it made none. */
  toolCalls?: AgentToolCall[];
}

/**
 * Typed content parts riding an agent turn (memo dev/39): validated
 * structured content produced by the runtime's tail protocol. Unknown part
 * types must be tolerated (forward compatibility with later contracts).
 */
export interface AgentSuggestedPromptsPart {
  type: "suggestedPrompts";
  /** The most useful next prompt — prefilled (editable) into the input. */
  primary: string;
  /** Up to 3 alternatives, rendered as the SUGGESTED PROMPTS chip row. */
  alternatives: string[];
}

/** An informational inline card (docs/08): plain data, no actions, no markup. */
export interface AgentCardPart {
  type: "card";
  kind: string; // "result" today; unknown kinds render the generic shell
  title: string;
  lines: string[];
}

/** The dev/50 two-lane suggestions part. Selection and confirmation live
 * client-side — the rows carry no actions (docs/06). */
export interface AgentDatasetCandidatesPart {
  type: "datasetCandidates";
  lanes: { external: AgentDatasetCandidateRow[]; catalog: AgentDatasetCandidateRow[] };
}

/** dev/72: a delegated task's compact entry on the PARENT's turn — the icon
 * notch links to the delegated agent's chat where the full trace lives.
 * Runtime-emitted only (like proposals); attachmentId null = no home. */
export interface AgentDelegationPart {
  type: "delegation";
  capability: string;
  coord: string;
  name: string;
  category: string;
  attachmentId: string | null;
  status: "ok" | "failed" | string;
  summary: string;
  /** What the delegated agent ran on, which may not be the parent's. */
  model?: string;
  llmLabel?: string;
}

export type AgentContentPart =
  | AgentSuggestedPromptsPart
  | AgentCardPart
  | AgentProposalPart
  | AgentDatasetCandidatesPart
  | AgentDataflowPlanPart
  | AgentDelegationPart
  | AgentSolveAttemptsPart
  | { type: string };

/** One persisted chat turn of an attachment's session. */
export interface AgentSessionTurn {
  role: "user" | "agent";
  text: string;
  ts?: string;
  /** Display-only failure marker; excluded from the agent's context. */
  error?: boolean;
  /** A client-side error turn's remedy (the refusal's own), never persisted. */
  remedy?: AgentRemedy;
  /** Execution record for agent turns produced by a run (memo dev/37). */
  execution?: AgentExecution;
  /** Typed content parts for agent turns (memo dev/39); absent on old turns. */
  content?: AgentContentPart[];
}

export interface AgentSession {
  attachmentId: string;
  sessionId: string | null;
  turns: AgentSessionTurn[];
}
