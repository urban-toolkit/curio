/**
 * A transcript: usage and execution records, the typed content parts a turn may carry, turns, and the session.
 *
 * Split out of `api/agentsApi.ts` (memo dev/142, F1); every shape keeps its name.
 */

import type { AgentDatasetCandidateRow, AgentRemedy } from "./evidence";
import type { AgentChangePart, AgentDataflowPlanPart, AgentProposalPart } from "./proposal";
import type { AgentRunSkillPins } from "./skills";
import type { AgentSolveAttemptsPart } from "./solve";

/** Actual provider-reported token usage (memo dev/37) — never an estimate. */
export interface AgentUsage {
  inputTokens: number;
  outputTokens: number;
}

/**
 * One tool call of a run (memo dev/41): the tool, how it ended, and, for a
 * granted call that did not succeed, the one-line reason the chat may show
 * under the reply (#447). Saved turns from before the reason have none.
 */
export interface AgentToolCall {
  tool: string;
  status: string;
  durationMs?: number;
  reason?: string;
  /** The egress policy refused it: its line stays under the reply (#447). */
  egress?: boolean;
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
    /** The skills its system turn held, each list only when it holds one. */
    skills?: AgentRunSkillPins;
  };
  usage: AgentUsage | null;
  durationMs?: number;
  /** `stopped`: someone stopped the turn; what it said and landed until
   * then stays. */
  status: "ok" | "error" | "stopped";
  /** Who stopped a stopped turn; null when the server ended it. */
  stoppedBy?: AgentTurnWriter | null;
  /** The tool calls the run made, in order; absent when it made none. */
  toolCalls?: AgentToolCall[];
  /** The skills skill.read loaded during the run; absent when it loaded none. */
  skillsLoaded?: string[];
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
 * Runtime-emitted only (like changes); attachmentId null = no home. */
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
  | AgentChangePart
  | AgentDatasetCandidatesPart
  | AgentDataflowPlanPart
  | AgentDelegationPart
  | AgentSolveAttemptsPart
  | { type: string };

/** Who wrote a person's message, in a chat the dataflow's owner and the
 * editors the owner invited share; named as a point of the dataflow's
 * history names a person. */
export interface AgentTurnWriter {
  kind: "person";
  account: string;
  name: string;
}

/** One persisted chat turn of an attachment's session. */
export interface AgentSessionTurn {
  role: "user" | "agent";
  text: string;
  ts?: string;
  /** Who wrote a user turn; absent on a turn from before writers were kept,
   * and on the local copy of the message this tab just sent. */
  by?: AgentTurnWriter;
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
  /** The asks as they stand: the running turn's first, then those waiting
   * their turn, in order. Absent from an old server. */
  asks?: AgentAskView[];
}

/** One event of an ask, as the room and a follow of the ask carry it
 * (`turn_jobs.EVENT`): `seq` is its place among the ask's events. Its
 * `event` is `asked`, `started` or `withdrawn`, one of its turn's own
 * stream's (`execution`, `delta`, `tool_result`, `change`, ..., `done`,
 * `error`), or, first in a follow, `snapshot`, whose `data` is the ask's
 * view. */
export interface AgentTurnEnvelope {
  projectId: string;
  attachmentId: string;
  askId: string;
  seq: number;
  event: string;
  data: Record<string, unknown>;
}

/** An ask as it stands, for a tab that opens while it waits or runs: its
 * message and writer, the reply's text so far and its turn's other events
 * so far, each with its `seq`; `seq` is its last event's. */
export interface AgentAskView {
  askId: string;
  by: AgentTurnWriter | null;
  message: string;
  state: "waiting" | "running" | "ended";
  askedAt: number;
  startedAt: number | null;
  seq: number;
  text: string;
  events: Array<{ seq: number; event: string; data: Record<string, unknown> }>;
}
