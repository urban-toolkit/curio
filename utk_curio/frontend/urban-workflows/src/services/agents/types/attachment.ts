/**
 * An attachment — a private agent instance on a node, the canvas or a connection — its live job and its target.
 *
 * Split out of `api/agentsApi.ts` (memo dev/142, F1); every shape keeps its name.
 */

import type { AgentDatasetSourceRecord } from "./evidence";
import type { AgentBuilderSession, AgentProposalSummary } from "./proposal";

/** A private agent instance attached to a node/canvas/connection. */
export interface AgentAttachment {
  attachmentId: string;
  coord: string;
  target: { kind: "node" | "canvas" | "connection"; targetId?: string };
  sessionId: string;
  revision: number;
  name: string;
  category: string | null;
  /** The capabilities its manifest declares: the chat offers each of its
   * features to any agent that declares the capability behind it. */
  capabilities?: string[];
  /** The name of the agent it hands a node to build to (node.build, through
   * its `delegatesTo`), for an agent that does not build nodes itself; null
   * otherwise. The candidates card's hand-off names it. */
  nodeBuildDelegate?: string | null;
  hooks: string[];
  /**
   * The attachment's initial intent: the user's edit when present, otherwise
   * the definition's instruction prompt resolved server-side from the actual
   * prompt source (never duplicated client-side). Null when the definition has
   * no prompt asset.
   */
  intent: string | null;
  /** True when the intent is a user edit (an override of the prompt source). */
  intentEdited: boolean;
  /**
   * The conversation title's custom portion (memo dev/25) — displayed as
   * "<name>: <title>" via `attachmentDisplayName`. Auto-generated server-side
   * from the first user message, or a manual rename. Null while untitled.
   */
  title: string | null;
  /** True when the title is a manual rename: it survives conversation clears
   * and is never overwritten by auto-generation. */
  titleEdited: boolean;
  /** The manifest's declared inputs (dev/38) — drives the client-side
   * grounded-context composer (memo dev/44). */
  reads?: string[];
  /** The attachment's single review proposal, newest wins (memo dev/41);
   * null/absent when none exists. Status wiring for the review card. */
  activeProposal?: AgentProposalSummary | null;
  /** dev/67-9: the plan the agent landed. */
  planProposal?: AgentProposalSummary | null;
  /** The Dataflow Builder orchestration session (dev/52 DR-2) — drives the
   * phase-aware builder panel; absent for every other agent. */
  builderSession?: AgentBuilderSession | null;
  /** dev/115 (DEC-073): the background job this server process holds for the
   * attachment — a Solve batch or a per-node Solve that outlives the request.
   * Null when none runs; the dock's running indicator and the chat panel's
   * re-attach derive from it. */
  liveJob?: AgentLiveJob | null;
  /** The nodes whose source this agent waits for the user to pick, or, for a
   * portal row picked, to download and import: a Dataset Finder's own node,
   * and the nodes whose candidates its chat asked for. Empty when it waits
   * for none. */
  waitsForYou?: string[];
  /** A Dataset Finder's record of its node's source; null for other agents. */
  sourceRecord?: AgentDatasetSourceRecord | null;
  /** Whether a node's Solve from this agent's chat goes ahead: the server's
   * own check, that an agent installed in the dataflow writes node content
   * for it. */
  solvesNodes?: boolean;
  /** The server's verdict on a Build & validate of this agent's plan: the
   * mode of the one that runs, or null when none does. A build its process
   * left behind, at a restart, runs no more. */
  buildRunning?: "step" | "auto" | null;
  /** A plan row's Solve that runs on the server on this agent's plan, the one
   * a pick goes on with among them: its ref and node, or null when none runs. */
  validating?: { ref: string; nodeId: string } | null;
}

/** dev/115: the liveness projection of a detached agent job — no event bodies. */
export interface AgentLiveJob {
  executionId: string;
  kind: "solve-batch" | "solve-node" | string;
  status: "running" | "done" | "error" | string;
  startedAt: number;
  heartbeatAt?: number;
  finishedAt?: number | null;
  events?: number;
}

export interface AgentTarget {
  kind: "node" | "canvas" | "connection";
  targetId?: string;
}
