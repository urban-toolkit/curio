/**
 * REST client for ``/api/agents`` - the three-scope Agent Catalog and its
 * lifecycle commands. Mirrors ``packagesApi.ts``: every request goes through
 * the shared ``apiFetch`` (Bearer header + JSON parse + error handling).
 *
 * The three scopes, named here as the drawer tabs name them:
 *  - Browse all  (catalog) → ``catalog()`` (the built-in definitions)
 *  - My imports  (account) → ``listImports()`` + ``import``/``removeImport``
 *  - In project → ``listProjectAgents()`` + ``install``/``uninstall``
 *
 * Import (account) and Install (project) are separate commands; neither chains.
 */

import { apiFetch } from "../../utils/authApi";
import { backendUrl } from "../../utils/backendUrl";

import { postSseStream } from "./agentStream";
import type {
  AgentApplyResult,
  AgentAttachment,
  AgentCard,
  AgentContentPart,
  AgentDatasetPick,
  AgentDatasetSelection,
  AgentInstallResponse,
  AgentListResponse,
  AgentPlanEdgesResult,
  AgentPlanNodeApplyResult,
  AgentProposalStatus,
  AgentSession,
  AgentSolveResult,
  AgentTarget,
  AgentUsage,
  CatalogSettingsResponse,
} from "./types";

const BACKEND_URL = backendUrl();

function coordParam(coord: string): string {
  return encodeURIComponent(coord);
}

export const agentsApi = {
  /** Browse all - the built-in definitions. Pass a projectId to mark the ones in the dataflow. */
  catalog(projectId?: string): Promise<AgentListResponse> {
    const q = projectId ? `?projectId=${encodeURIComponent(projectId)}` : "";
    return apiFetch(`/api/agents/catalog${q}`);
  },

  /** Every catalog setting with this account's value and who reads it. */
  catalogSettings(): Promise<CatalogSettingsResponse> {
    return apiFetch("/api/agents/settings");
  },

  /** Change settings by key; null restores a setting's default. Nothing is
   * saved unless every value is valid. */
  updateCatalogSettings(changes: Record<string, unknown | null>): Promise<CatalogSettingsResponse> {
    return apiFetch("/api/agents/settings", {
      method: "PUT",
      body: JSON.stringify(changes),
    });
  },

  /** Account "My imports". Pass a projectId to mark which are in the dataflow
   * that project (memo dev/47 — the lockfile is the one source of truth). */
  listImports(projectId?: string): Promise<AgentListResponse> {
    const q = projectId ? `?projectId=${encodeURIComponent(projectId)}` : "";
    return apiFetch(`/api/agents/imports${q}`);
  },

  /** Record a definition coordinate in My imports (does not add it to a dataflow). */
  import(coord: string): Promise<{ coord: string; imported: boolean }> {
    return apiFetch("/api/agents/imports", {
      method: "POST",
      body: JSON.stringify({ coord }),
    });
  },

  /**
   * Upload a user-authored definition (memo dev/36): the manifest plus its
   * prompt texts. The server forces trust to "imported", stamps digests from
   * the bytes, and rejects duplicates/oversize/mismatched files. Returns the
   * new (publishable) My imports card. Nothing auto-installs or publishes.
   */
  uploadImport(
    manifest: Record<string, unknown>,
    prompts: Record<string, string>
  ): Promise<AgentCard> {
    return apiFetch("/api/agents/imports/upload", {
      method: "POST",
      body: JSON.stringify({ manifest, prompts }),
    });
  },

  /** Drop a coordinate from My imports. */
  removeImport(coord: string): Promise<{ coord: string; imported: boolean }> {
    return apiFetch(`/api/agents/imports/${coordParam(coord)}`, { method: "DELETE" });
  },

  /** Agents installed in a project's ``dataflow.agents`` lockfile. */
  listProjectAgents(projectId: string): Promise<AgentListResponse> {
    return apiFetch(`/api/agents/projects/${encodeURIComponent(projectId)}`);
  },

  /** Install a definition into a project (explicit; never auto-imports).
   * dev/106: the server installs the agent's ``requiresAgents`` closure with
   * it in one write, or 409s naming an unresolvable dependency. */
  installToProject(projectId: string, coord: string): Promise<AgentInstallResponse> {
    return apiFetch(`/api/agents/projects/${encodeURIComponent(projectId)}/install`, {
      method: "POST",
      body: JSON.stringify({ coord }),
    });
  },

  /** Remove a definition from a project's lockfile. */
  uninstallFromProject(projectId: string, coord: string): Promise<{ agents: string[] }> {
    return apiFetch(`/api/agents/projects/${encodeURIComponent(projectId)}/${coordParam(coord)}`, {
      method: "DELETE",
    });
  },

  /** Publish an owned, imported definition to the Agent Catalog (imported-only). */
  publish(coord: string): Promise<{ coord: string; published: boolean }> {
    return apiFetch("/api/agents/publications", {
      method: "POST",
      body: JSON.stringify({ coord }),
    });
  },

  /** Unpublish an owned definition (owner only). */
  unpublish(coord: string): Promise<{ coord: string; published: boolean }> {
    return apiFetch(`/api/agents/publications/${coordParam(coord)}`, { method: "DELETE" });
  },

  /**
   * One agent's full definition: manifest plus every prompt text.
   *
   * Agents had an import (`uploadImport`) with no export on the other side, so
   * a definition could go into a Curio and never come back out - and the
   * details screen could describe an agent's prompts only by not showing them.
   * Returns the exact shape `uploadImport` consumes, so the two round-trip.
   */
  readDefinition(
    coord: string
  ): Promise<{ manifest: Record<string, unknown>; prompts: Record<string, string> }> {
    return apiFetch(`/api/agents/definitions/${coordParam(coord)}`);
  },

  /** List the project's private attachments. */
  listAttachments(projectId: string): Promise<{ attachments: AgentAttachment[] }> {
    return apiFetch(`/api/agents/projects/${encodeURIComponent(projectId)}/attachments`);
  },

  /** Attach an installed template to a target (requires it installed; never auto-installs). */
  attach(projectId: string, coord: string, target: AgentTarget): Promise<AgentAttachment> {
    return apiFetch(`/api/agents/projects/${encodeURIComponent(projectId)}/attachments`, {
      method: "POST",
      body: JSON.stringify({ coord, target }),
    });
  },

  /** Detach a private instance. */
  detachAttachment(
    projectId: string,
    attachmentId: string
  ): Promise<{ attachmentId: string; detached: boolean }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: "DELETE" }
    );
  },

  /** Set/clear the attachment's editable intent; null/empty restores the prompt source. */
  updateAttachmentIntent(
    projectId: string,
    attachmentId: string,
    intent: string | null
  ): Promise<AgentAttachment> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: "PATCH", body: JSON.stringify({ intent }) }
    );
  },

  /** Manually rename the conversation title (memo dev/25): non-empty only;
   * a manual title always wins over auto-generation and survives clears. */
  updateAttachmentTitle(
    projectId: string,
    attachmentId: string,
    title: string
  ): Promise<AgentAttachment> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: "PATCH", body: JSON.stringify({ title }) }
    );
  },

  /** Apply a pending review proposal (memo dev/41) — the only mutation path;
   * revision-safe (409 when the target drifted, marking the proposal stale). */
  applyProposal(
    projectId: string,
    attachmentId: string,
    proposalId: string
  ): Promise<AgentApplyResult> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}/apply`,
      { method: "POST" }
    );
  },

  /** Apply ONE planned node from a pending plan proposal (dev/67-5,
   * Simulation Mode: create). The proposal stays pending until every ref is
   * applied or it is dismissed; edges are the connection stage's (67-8). */
  applyPlanNode(
    projectId: string,
    attachmentId: string,
    proposalId: string,
    ref: string
  ): Promise<AgentPlanNodeApplyResult> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}/apply-node`,
      { method: "POST", body: JSON.stringify({ ref }) }
    );
  },

  /** dev/126: record the user's confirmed dataset selection for the node this
   * Dataset Finder is attached to. The picks carry identifiers only — the
   * server resolves them against the candidates it proposed. */
  recordDatasetSelection(
    projectId: string,
    attachmentId: string,
    picks: AgentDatasetPick[]
  ): Promise<AgentDatasetSelection> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/dataset-selection`,
      { method: "POST", body: JSON.stringify({ picks }) }
    );
  },

  /** Apply plan edges — the connection review stage (dev/67-8). Omitted
   * indices apply every not-yet-applied edge; refusals are per-edge and
   * named; `createdEdges` feeds the canvas bridge. */
  applyPlanEdges(
    projectId: string,
    attachmentId: string,
    proposalId: string,
    indices?: number[]
  ): Promise<AgentPlanEdgesResult> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}/apply-edges`,
      { method: "POST", body: JSON.stringify(indices ? { edges: indices } : {}) }
    );
  },

  /** Edit one planned node's goal before creation (dev/67-5): an audited
   * review-stage overlay — the pinned plan bytes stay immutable. */
  savePlanGoal(
    projectId: string,
    attachmentId: string,
    proposalId: string,
    ref: string,
    goal: string
  ): Promise<{
    proposalId: string;
    ref: string;
    goal: string;
    editedGoals: Record<string, string>;
  }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}/plan-goals`,
      { method: "PATCH", body: JSON.stringify({ ref, goal }) }
    );
  },

  /** Dismiss a pending review proposal without applying it. */
  dismissProposal(
    projectId: string,
    attachmentId: string,
    proposalId: string
  ): Promise<{ attachmentId: string; proposalId: string; status: AgentProposalStatus }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}`,
      { method: "DELETE" }
    );
  },

  /** The attachment's persisted chat transcript (its session history). */
  getSession(projectId: string, attachmentId: string): Promise<AgentSession> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/session`
    );
  },

  /** Clear the transcript; the attachment and its session id are kept. */
  clearSession(projectId: string, attachmentId: string): Promise<AgentSession> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/session`,
      { method: "DELETE" }
    );
  },

  /** Run one turn of an attached agent and get its reply. */
  runAttachment(
    projectId: string,
    attachmentId: string,
    message: string,
    /** Ephemeral grounded context (memo dev/44) — composed fresh per send. */
    context?: string | null
  ): Promise<{
    attachmentId: string;
    coord: string;
    reply: string;
    /** Execution identity + Actual usage (memo dev/37); absent on old servers. */
    executionId?: string;
    usage?: AgentUsage | null;
    /** The run's wall-clock duration (memo dev/80); absent on old servers. */
    durationMs?: number;
    /** Typed content parts (memo dev/39); absent on old servers. */
    content?: AgentContentPart[];
  }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/run`,
      { method: "POST", body: JSON.stringify(context ? { message, context } : { message }) }
    );
  },

  /**
   * Run one turn and stream the reply as it is generated (memo dev/22).
   *
   * POSTs to the SSE endpoint via raw fetch (EventSource cannot POST), calls
   * `onDelta` per text chunk, and resolves on the `done` event with the full
   * reply plus the run's execution identity and Actual usage when the server
   * sends them (memo dev/37; absent from old servers). Unknown event names are
   * skipped, so the parser tolerates future envelope additions. Pre-stream
   * failures (404, 400, …) throw an Error carrying `status`/`body` like
   * `apiFetch`; a mid-stream `error` event throws too.
   */
  async runAttachmentStream(
    projectId: string,
    attachmentId: string,
    message: string,
    onDelta: (text: string) => void,
    /** Optional observer for the dev/41 tool/review events (`tool_requested`,
     * `tool_started`, `tool_result`, `review_required`) and the dev/80
     * interim `usage` events — transient display only; the durable state
     * arrives with `done`/rehydration. */
    onEvent?: (name: string, payload: Record<string, unknown>) => void,
    /** Ephemeral grounded context (memo dev/44) — composed fresh per send. */
    context?: string | null
  ): Promise<{
    reply: string;
    executionId?: string;
    usage?: AgentUsage | null;
    /** The run's wall-clock duration (memo dev/80); absent on old servers. */
    durationMs?: number;
    content?: AgentContentPart[];
  }> {
    let reply: string | null = null;
    let executionId: string | undefined;
    let usage: AgentUsage | null | undefined;
    let durationMs: number | undefined;
    let content: AgentContentPart[] | undefined;

    await postSseStream(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/run/stream`,
      context ? { message, context } : { message },
      (event, raw) => {
        const payload = raw as {
          text?: string;
          reply?: string;
          error?: string;
          executionId?: string;
          usage?: AgentUsage | null;
          durationMs?: number;
          parts?: AgentContentPart[];
          content?: AgentContentPart[];
        };
        if (event === "delta" && payload.text) onDelta(payload.text);
        else if (event === "execution") executionId = payload.executionId;
        else if (event === "content") content = payload.parts;
        else if (
          event === "tool_requested" ||
          event === "tool_started" ||
          event === "tool_result" ||
          event === "review_required" ||
          event === "delegate_requested" ||
          event === "delegate_started" ||
          event === "delegate_result" ||
          event === "plan_revision" ||
          // dev/80: interim provider-reported usage sums, once per loop round.
          event === "usage"
        )
          onEvent?.(event, payload as Record<string, unknown>);
        else if (event === "done") {
          reply = payload.reply ?? "";
          executionId = payload.executionId ?? executionId;
          usage = payload.usage;
          durationMs = payload.durationMs;
          content = payload.content ?? content;
        } else if (event === "error") throw new Error(payload.error || "agent run failed");
      }
    );
    if (reply === null) throw new Error("stream ended without a reply");
    return { reply, executionId, usage, durationMs, content };
  },

  /**
   * The Solve batch streamed (dev/63, the DEC-021 user slice): per-node
   * lifecycle events (`solve_started`, `node_started`, `node_result`) reach
   * `onEvent` as they happen; resolves with the terminal `done` payload —
   * the same shape the blocking endpoint returns, plus `cancelled` /
   * `notAttempted`. A mid-stream `error` event throws. `signal` aborts the
   * local reader; the server stops dispatch at its next node boundary.
   */
  async solveAttachmentStream(
    projectId: string,
    attachmentId: string,
    onEvent: (name: string, payload: Record<string, unknown>) => void,
    nodeIds?: string[],
    signal?: AbortSignal,
    /** dev/67-6: "propose" mints reviewed content proposals instead of
     * writing — the Simulation Mode solve stage. Default: classic write. */
    mode?: "write" | "propose"
  ): Promise<AgentSolveResult> {
    let result: AgentSolveResult | null = null;
    await postSseStream(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/solve/stream`,
      { ...(nodeIds ? { nodeIds } : {}), ...(mode ? { mode } : {}) },
      (event, payload) => {
        if (event === "done") result = payload as unknown as AgentSolveResult;
        else if (event === "error")
          throw new Error((payload as { error?: string }).error || "solve failed");
        else onEvent(event, payload);
      },
      signal
    );
    if (result === null) throw new Error("solve stream ended without a result");
    return result;
  },

  /**
   * The Simulation Mode driver (dev/67-9, DEC-054): `step` performs the next
   * single action; `auto` chains create → validate → auto-approve-on-PASS →
   * connections, pausing on any failure. Canvas mutations ride the stream
   * (`node_created`/`node_content_applied`/`edges_created`) — the caller
   * dispatches them. Resolves with the `done` payload (status
   * completed|stepped|paused|cancelled + builderSession).
   */
  async simulate(
    projectId: string,
    attachmentId: string,
    mode: "step" | "auto",
    onEvent: (name: string, payload: Record<string, unknown>) => void,
    signal?: AbortSignal
  ): Promise<Record<string, unknown>> {
    let result: Record<string, unknown> | null = null;
    await postSseStream(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/simulate`,
      { mode },
      (event, payload) => {
        if (event === "done") result = payload;
        else if (event === "error")
          throw new Error((payload as { error?: string }).error || "simulation failed");
        else onEvent(event, payload);
      },
      signal
    );
    if (result === null) throw new Error("simulation ended without a result");
    return result;
  },

  /**
   * Run the dataflow THROUGH one node (dev/71): the saved content executes
   * through its upstream chain; results journal as real runs (readable by
   * agents via node.runtime.read). Streams `run_started`/`node_executed`;
   * resolves with the `done` report {ok, order, nodes, blocker, error}.
   */
  async runNode(
    projectId: string,
    attachmentId: string,
    target: { ref?: string; nodeId?: string },
    onEvent: (name: string, payload: Record<string, unknown>) => void,
    signal?: AbortSignal
  ): Promise<Record<string, unknown>> {
    let result: Record<string, unknown> | null = null;
    await postSseStream(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/run-node`,
      target,
      (event, payload) => {
        if (event === "done") result = payload;
        else if (event === "error")
          throw new Error((payload as { error?: string }).error || "the run failed");
        else onEvent(event, payload);
      },
      signal
    );
    if (result === null) throw new Error("the run ended without a result");
    return result;
  },

  /** Cancel a running simulation (dev/67-9): stops at the next boundary. */
  cancelSimulate(
    projectId: string,
    attachmentId: string
  ): Promise<{ attachmentId: string; cancelRequested: boolean }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/simulate/cancel`,
      { method: "POST" }
    );
  },

  /**
   * Generate → execute-through → validate → self-correct → propose for ONE
   * node (dev/67-7, Simulation Mode: validate). Streams lifecycle events
   * (`validation_started`, `generation_round`, `node_executed`,
   * `round_verdict`) and resolves with the `done` payload — verdict,
   * evidence, rounds, and the minted proposal id (PASS or FAIL: the user
   * decides on the review card).
   */
  async validateNode(
    projectId: string,
    attachmentId: string,
    target: { ref?: string; nodeId?: string },
    onEvent: (name: string, payload: Record<string, unknown>) => void,
    signal?: AbortSignal
  ): Promise<Record<string, unknown>> {
    let result: Record<string, unknown> | null = null;
    await postSseStream(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/validate-node`,
      target,
      (event, payload) => {
        if (event === "done") result = payload;
        else if (event === "error")
          throw new Error((payload as { error?: string }).error || "validation failed");
        else onEvent(event, payload);
      },
      signal
    );
    if (result === null) throw new Error("validation ended without a result");
    return result;
  },

  /**
   * dev/115 (DEC-073, Amendment A2): the per-node Solve — run the node's
   * CURRENT code in the sandbox, fix what fails, run again; a node with
   * content lands as an already-executed content review, an empty node is
   * written on PASS. Streams `solve_node_started` → `generation_round` /
   * `node_executed` / `round_verdict` → `done`. Detached on the server:
   * closing the stream does not stop the run (`attachJobStream` re-attaches).
   */
  async solveNodeStream(
    projectId: string,
    attachmentId: string,
    nodeId: string,
    onEvent: (name: string, payload: Record<string, unknown>) => void,
    signal?: AbortSignal
  ): Promise<Record<string, unknown>> {
    let result: Record<string, unknown> | null = null;
    await postSseStream(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/solve-node`,
      { nodeId },
      (event, payload) => {
        if (event === "done") result = payload;
        else if (event === "error")
          throw new Error((payload as { error?: string }).error || "solve failed");
        else onEvent(event, payload);
      },
      signal
    );
    if (result === null) throw new Error("solve-node ended without a result");
    return result;
  },

  /**
   * dev/115 (DEC-021 single-process slice): re-attach to the attachment's
   * background job — replays every event so far (a leading `job` event
   * carries the liveness projection), then tails live ones. Resolves with
   * the `done` payload when the job finishes, or null when the replay ended
   * without one (an errored job). 404 when there is nothing to attach to.
   */
  async attachJobStream(
    projectId: string,
    attachmentId: string,
    onEvent: (name: string, payload: Record<string, unknown>) => void,
    signal?: AbortSignal
  ): Promise<Record<string, unknown> | null> {
    let result: Record<string, unknown> | null = null;
    await postSseStream(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/jobs/stream`,
      undefined,
      (event, payload) => {
        if (event === "done") result = payload;
        else if (event === "error")
          throw new Error((payload as { error?: string }).error || "the background job failed");
        else onEvent(event, payload);
      },
      signal,
      "GET"
    );
    return result;
  },

  /** Cancel a running Solve (dev/63): new children stop dispatching at the
   * next node boundary; in-flight children finish and their results persist;
   * undispatched targets revert to pending. 409 when nothing is running. */
  cancelSolve(
    projectId: string,
    attachmentId: string
  ): Promise<{ attachmentId: string; cancelRequested: boolean }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/solve/cancel`,
      { method: "POST" }
    );
  },
};
