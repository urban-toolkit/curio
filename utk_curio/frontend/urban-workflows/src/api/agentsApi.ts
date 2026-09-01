import { apiFetch, getToken } from "../utils/authApi";

const BACKEND_URL = process.env.BACKEND_URL || "";

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

/** The deployment-wide provider default, with no secret in it. */
export interface ProviderDefault {
  apiType: string | null;
  baseUrl: string | null;
  model: string | null;
  hasApiKey: boolean;
}

/** One agent card as returned by the backend (camelCase). */
export interface AgentCard {
  id: string; // e.g. "agent.node-explainer"
  version: string;
  dirName: string; // "<id>@<version>"
  name: string;
  category: string; // data | node | canvas | package | evaluate
  purpose: string;
  capabilities: string[];
  hooks: string[]; // compatible target kinds: node | canvas | connection
  provenance: { publisher: string; trust: string | null };
  imported: boolean;
  installedInProject: boolean;
  published: boolean;
  /** Eligible for Publish: an owned, store-backed definition (not a built-in). */
  publishable: boolean;
  /** Which list this card came from. Same vocabulary as the drawer's tabs
   *  (AgentScope) - one set of words for one idea. */
  scope: "browse" | "imports" | "installed";
  /** dev/106: server-resolved hard dependencies (``requiresAgents``) — what an
   * Install adds alongside this agent. ``[]`` for every leaf agent. */
  requiresAgents: AgentRequirement[];
}

/** One direct hard dependency of an agent (dev/106). */
export interface AgentRequirement {
  id: string;
  name: string;
  /** The visible coordinate an install would add; null when visible nowhere. */
  coord: string | null;
  visible: boolean;
  installedInProject: boolean;
}

/** dev/106: the install response — the lockfile plus what this call added. */
export interface AgentInstallResponse {
  agents: string[];
  /** Coords newly added by this call, root first (empty on an idempotent re-install). */
  installed: string[];
  /** The root's required closure (installed or not). */
  required: string[];
}

/** Facet counts, keyed by facet then by value. Every key is present at zero,
 *  so a rail renders a complete set of rows rather than only the populated
 *  ones - the same contract `GET /api/datasets/catalog` returns. */
export interface AgentCatalogFacets {
  category: Record<string, number>;
  origin: Record<string, number>;
}

interface AgentListResponse {
  /** The rows. `agents` is the historical name and still returned; `items`
   *  matches the other catalogs and is what new surfaces should read. */
  agents: AgentCard[];
  items?: AgentCard[];
  /** Present on `/catalog` only; the scoped lists have nothing to facet. */
  facets?: AgentCatalogFacets;
}

/** A private agent instance attached to a node/canvas/connection. */
export interface AgentAttachment {
  attachmentId: string;
  coord: string;
  target: { kind: "node" | "canvas" | "connection"; targetId?: string };
  sessionId: string;
  revision: number;
  name: string;
  category: string | null;
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
  /** dev/67-9: the plan proposal PARKED while per-node content reviews cycle
   * through the active slot — still pending, still addressable. */
  planProposal?: AgentProposalSummary | null;
  /** The Dataflow Builder orchestration session (dev/52 DR-2) — drives the
   * phase-aware builder panel; absent for every other agent. */
  builderSession?: AgentBuilderSession | null;
}

/** The activeProposal mirror row (dev/41; dev/67-5/8/9 extensions). */
export interface AgentProposalSummary {
  proposalId: string;
  tool: string;
  nodeId: string;
  summary: string;
  status: AgentProposalStatus;
  /** dev/67-5 (plan proposals): review-stage goal edits, ref-keyed. */
  editedGoals?: Record<string, string>;
  /** dev/67-5 (plan proposals): refs already applied per-node. */
  appliedRefs?: string[];
  /** dev/67-8 (plan proposals): edge index → planned|applied|refused. */
  edgeStates?: Record<string, string>;
}

/** dev/52 DR-2: the persisted Plan → Solve state riding the attachment.
 * dev/67-5 adds the per-node Simulation Mode ledger. */
export interface AgentBuilderSession {
  phase: "idle" | "plan_review" | "simulating" | "applied" | "solving" | "ready";
  planProposalId?: string;
  appliedPlanId?: string;
  /** Plan-created node id → its solve status. */
  nodeRuns?: Record<string, "pending" | "solving" | "solved" | "failed" | "skipped">;
  /** dev/67-5: plan ref → its per-node lifecycle state. */
  nodeStates?: Record<string, string>;
  /** dev/67-5: plan ref → the created node's real id. */
  nodeIds?: Record<string, string>;
  /** dev/67-8: edge index → planned|applied|refused. */
  edgeStates?: Record<string, string>;
  /** dev/67-9: the ref the driver is working on, while running. */
  currentRef?: string;
  /** dev/67-9: why the sequence paused — a plain reason with a next action. */
  pauseReason?: { kind: string; ref?: string; proposalId?: string; message: string };
  /** dev/67-9: ref → its validated content proposal. dev/72 homes the
   * proposal on the node's own agent — the object shape carries where it
   * lives; legacy string values mean builder-homed. */
  nodeProposals?: Record<
    string,
    string | { proposalId: string; attachmentId?: string | null }
  >;
}

/** Actual provider-reported token usage (memo dev/37) — never an estimate. */
export interface AgentUsage {
  inputTokens: number;
  outputTokens: number;
}

/**
 * The per-run execution record riding an agent turn (memo dev/37): identity,
 * DEC-031 reproducibility pins, duration, status, and Actual usage (null when
 * the provider reports none). Turns that predate the record simply lack it.
 */
export interface AgentExecution {
  executionId: string;
  pins?: {
    coord?: string;
    promptSha256?: string | null;
    intentEdited?: boolean;
    provider?: string;
    model?: string;
    policy?: Record<string, number | null>;
  };
  usage: AgentUsage | null;
  durationMs?: number;
  status: "ok" | "error";
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

/** One dev/50 candidate row (docs/06 row contract) — informational metadata,
 * bounded and scheme-allowlisted server-side, sanitized again at render. */
export interface AgentDatasetCandidateRow {
  name: string;
  sourceType: "api" | "endpoint" | "portal" | "catalog" | "document" | "database";
  url?: string;
  provider?: string;
  format?: string;
  coverage?: string;
  requirement?: string;
  fit?: { score: number; rationale: string };
  /** Catalog lane only: the id dataset.install proposals reference. */
  datasetId?: string;
  installed?: boolean;
  /** dev/67-4 (DEC-053): the deterministic verification verdict — external
   * rows only; runtime-probed through the egress policy, never model-claimed. */
  verification?: {
    status: "verified" | "unreachable" | "refused" | "unverified" | string;
    detail?: string;
    httpStatus?: number;
    provider?: string;
    datasetId?: string;
    datasetName?: string;
    columns?: string[];
    checkedAt?: string;
  };
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
}

export type AgentProposalStatus =
  | "pending"
  | "applied"
  | "dismissed"
  | "superseded"
  | "stale";

/**
 * A review-before-apply proposal (memo dev/41): runtime-minted when a granted
 * mutate tool is requested. Only the authenticated apply endpoint executes
 * it; the part is the transcript's display record of the outcome.
 */
export interface AgentProposalPart {
  type: "proposal";
  proposalId: string;
  /** "node.content.write" | "node.create" | "node.template.create" | "project.install" | future kinds. */
  tool: string;
  summary: string;
  /** The full proposed content (plain text — rendered inert). */
  preview: string;
  /** Tool-specific revision-safety basis (dev/41 digest pins; dev/48 nodeType/coord/slug pins). */
  pins: Record<string, string>;
  status: AgentProposalStatus;
  /** node.template.create only (dev/48 §3.2b): the model's written reasoning — what the user judges. */
  justification?: string;
  /** package.draft.apply only (dev/91 §5): the backend trust edge stated on
   * the card — declared handlers, permission strings, and network posture. */
  backend?: {
    handlers: Array<{ name: string; timeoutClass?: string }>;
    permissions: string[];
    network: boolean;
  };
  /** package.draft.apply only (dev/96): the bounded diff/dependencies/preview
   * slice the card renders — every capped list carries its TRUE total, so
   * overflow is always statable ("…and N more"), never silent. */
  draft?: {
    mode: string;
    target: string;
    files: { added: string[]; modified: string[]; addedTotal: number;
             modifiedTotal: number; preservedTotal: number };
    templates: { added: string[]; modified: string[]; addedTotal: number;
                 modifiedTotal: number; preservedTotal: number };
    dependencies?: {
      /** dev/97: where the python deps will live — "overlay" (isolated,
       * backend handlers only), "both" (plus the shared interpreter for
       * warm-sandbox python templates), or "host". */
      home?: string;
      python: Array<{ name: string; constraint: string }>;
      pythonTotal: number;
      js: Array<{ name: string; version: string }>;
      jsTotal: number;
      findings: Array<{ severity: string; code: string; message: string }>;
      findingsTotal: number;
      blocked: boolean;
    };
    preview?: {
      status: string;
      reasons: string[];
      reasonsTotal: number;
      templates: Array<{ templateId: string; ok: boolean; failedStates: string[] }>;
      runnerVersion: string;
    };
    requestedNodes?: { rows: Array<{ title: string; color: string }>; total: number };
  };
  /** node.template.create only: the proposed type definition summary. */
  template?: { label: string; engine: string; description?: string };
  /** dev/67-7: the validation verdict riding a validated content proposal. */
  validation?: {
    verdict: "pass" | "fail" | string;
    rounds: number;
    evidence?: {
      kind?: string;
      detail?: string;
      stderrTail?: string;
      outputDataType?: string;
      blocker?: string;
      blockerLabel?: string;
      warnings?: string;
      goal?: string;
    };
  };
  /** dataflow.plan.write only (dev/52): the plan's display copy for the review card. */
  plan?: {
    goal: string;
    templateId?: string;
    nodes: Array<{
      ref: string;
      nodeType: string;
      title: string;
      intent: string;
      /** dev/67-5: expected input/output one-liner for the plan card. */
      expects?: string;
    }>;
    edgeCount: number;
    /** dev/67-8: the connection stage's labeled, index-stable edge rows. */
    edges?: Array<{
      from: string;
      to: string;
      toHandle?: string;
      fromLabel: string;
      toLabel: string;
    }>;
    /** dev/59 (DEC-049.2): removals reviewed by NAME — every victim listed
     * with a content flag; present only on destructive revisions. */
    removals?: Array<{ id: string; label: string; nodeType?: string; contentChars: number }>;
    removedEdgeCount?: number;
    cascadeCount?: number;
  };
}

/** dev/52 DR-1: the model-emitted typed plan part (informational until the
 * runtime mints the reviewed proposal from it). */
export interface AgentDataflowPlanPart {
  type: "dataflowPlan";
  goal: string;
  templateId?: string;
  nodes: Array<{ ref: string; nodeType: string; title: string; intent: string; content?: string }>;
  edges: Array<{ from: string; to: string }>;
}

/** The node payload an apply response carries for the canvas bridge (dev/48 §3.3). */
export interface AgentCreatedNodePayload {
  id: string;
  type: string;
  content: string;
  goal?: string;
  x: number;
  y: number;
  /** dev/89: optional display title persisted on the spec node. */
  title?: string;
  /** dev/89: canonical persisted appearance (backend-normalized). */
  metadata?: { appearance?: { backgroundColor?: string } };
}

/** Apply-endpoint response (dev/41 base + the dev/48/52 bridge payloads). */
export interface AgentApplyResult {
  attachmentId: string;
  proposalId: string;
  status: AgentProposalStatus;
  mutationApplied?: boolean;
  /** node.create / node.template.create: the inserted node, for the live canvas. */
  createdNode?: AgentCreatedNodePayload;
  /** node.template.create: the registered template ({id, label, packageDir, …}). */
  createdTemplate?: { id: string; label: string; packageDir?: string };
  /** node.content.write: the applied content, for the live node. */
  appliedContent?: { nodeId: string; content: string };
  /** project.install: the installed agent coordinate. */
  installedCoord?: string;
  /** dataflow.plan.write (dev/52; removals per dev/59): the applied plan
   * graph delta, for the live canvas. */
  appliedGraph?: {
    nodes: AgentCreatedNodePayload[];
    edges: Array<{
      id: string;
      source: string;
      target: string;
      /** dev/67-3: explicit handles from the apply (merge slots in_N). */
      sourceHandle?: string;
      targetHandle?: string;
    }>;
    removedNodeIds?: string[];
    removedEdgeIds?: string[];
  };
  /** dataflow.plan.write: the builder session after apply. */
  builderSession?: AgentBuilderSession | null;
  /** package.install / package.draft.apply: the installed package. */
  installedPackage?: { dirName: string; name: string; replaced?: boolean };
  /** package.draft.apply (dev/89): the requested nodes inserted after the
   * reviewed install — painted only after the registry refresh. */
  createdNodes?: AgentCreatedNodePayload[];
  /** package.draft.apply (dev/89): the frontend must refresh the package/
   * behavior/template registries BEFORE painting createdNodes. */
  requiresRegistryRefresh?: boolean;
  /** package.install (dev/105 A3): the note proposals the apply queued below
   * the install card, in order — the caller applies them one at a time so
   * each note lands before the next card is applied. */
  followUpProposals?: string[];
}

/** dev/67-5 apply-node response: one created node + the per-node ledger. */
export interface AgentPlanNodeApplyResult {
  attachmentId: string;
  proposalId: string;
  status: "pending" | "already-applied";
  ref: string;
  /** already-applied only: the existing node's id. */
  nodeId?: string;
  /** The created node, for the canvas bridge (absent on already-applied). */
  createdNode?: AgentCreatedNodePayload;
  appliedRefs: string[];
  /** dev/71: edges the progressive sweep drew in THIS apply (bridge payload). */
  createdEdges?: Array<{
    id: string;
    source: string;
    target: string;
    sourceHandle?: string;
    targetHandle?: string;
  }>;
  /** dev/71: the sweep's per-edge outcomes (index-keyed; refusals named). */
  edgeResults?: Record<string, { status: string; reason?: string; fromLabel?: string; toLabel?: string }>;
  edgeStates?: Record<string, string>;
  /** dev/71: the auto-attached Node Builder's attachment id (null = skipped). */
  attachedAgentId?: string | null;
  builderSession?: AgentBuilderSession | null;
}

/** dev/67-8 apply-edges response: per-edge outcomes + the bridge payload. */
export interface AgentPlanEdgesResult {
  attachmentId: string;
  proposalId: string;
  status: AgentProposalStatus;
  results: Record<
    string,
    {
      status: "applied" | "refused" | "already-applied";
      fromLabel: string;
      toLabel: string;
      edgeId?: string;
      targetHandle?: string;
      reason?: string;
      note?: string;
    }
  >;
  edgeStates: Record<string, string>;
  createdEdges: Array<{
    id: string;
    source: string;
    target: string;
    sourceHandle?: string;
    targetHandle?: string;
  }>;
  builderSession?: AgentBuilderSession | null;
}

/** dev/52 Solve response: per-node outcomes + live-canvas content payloads.
 * dev/63 adds the streamed batch's cancellation facts. */
export interface AgentSolveResult {
  attachmentId: string;
  executionId: string;
  results: Record<string, { status: "solved" | "failed" | "skipped"; error?: string }>;
  appliedContents: Array<{ nodeId: string; content: string }>;
  builderSession: AgentBuilderSession;
  /** dev/63: true when the batch was cancelled (endpoint or disconnect). */
  cancelled?: boolean;
  /** dev/63: targets never dispatched — reverted to pending. */
  notAttempted?: string[];
  /** dev/106: the batch-level failure reason (the missing-specialist case) —
   * the same text every node's `error` carries; the Solve card shows it once. */
  reason?: string;
}

export type AgentContentPart =
  | AgentSuggestedPromptsPart
  | AgentCardPart
  | AgentProposalPart
  | AgentDatasetCandidatesPart
  | AgentDataflowPlanPart
  | AgentDelegationPart
  | { type: string };

/** One persisted chat turn of an attachment's session. */
export interface AgentSessionTurn {
  role: "user" | "agent";
  text: string;
  ts?: string;
  /** Display-only failure marker; excluded from the agent's context. */
  error?: boolean;
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

export interface AgentTarget {
  kind: "node" | "canvas" | "connection";
  targetId?: string;
}

/** ``@``/``.`` are legal in a coordinate but must be escaped in a path param. */
/**
 * POST to an SSE endpoint and dispatch each parsed event frame (the dev/22
 * transport, shared by the chat and Solve streams — dev/63). Pre-stream
 * failures (404, 400, …) throw an Error carrying `status`/`body` like
 * `apiFetch`; frame payloads are JSON-decoded before dispatch.
 */
async function postSseStream(
  path: string,
  body: unknown,
  onFrame: (event: string, payload: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({} as Record<string, unknown>));
    const err = new Error((errBody as { error?: string }).error || `HTTP ${res.status}`);
    (err as Error & { status?: number; body?: unknown }).status = res.status;
    (err as Error & { status?: number; body?: unknown }).body = errBody;
    throw err;
  }
  if (!res.body) throw new Error("streaming not supported");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const handleFrame = (frame: string) => {
    let event = "message";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7).trim();
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (!data) return;
    onFrame(event, JSON.parse(data) as Record<string, unknown>);
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep = buffer.indexOf("\n\n");
    while (sep >= 0) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      handleFrame(frame);
      sep = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) handleFrame(buffer);
}

function coordParam(coord: string): string {
  return encodeURIComponent(coord);
}

export const agentsApi = {
  /** Browse all - the built-in definitions. Pass a projectId to mark the ones in the dataflow. */
  catalog(projectId?: string): Promise<AgentListResponse> {
    const q = projectId ? `?projectId=${encodeURIComponent(projectId)}` : "";
    return apiFetch(`/api/agents/catalog${q}`);
  },

  /** What a user inherits when they configure no provider of their own.
   *
   * The launcher's --llm-provider / --llm-base-url / --llm-model write exactly
   * these, so AI Settings can present the deployment's choice as the inherited
   * value rather than inventing a placeholder. The key is a boolean only. */
  providerDefault(): Promise<ProviderDefault> {
    return apiFetch("/api/agents/provider-default");
  },

  /** The models an OpenAI-compatible endpoint reports it serves.
   *
   * POSTed rather than GET because AI Settings calls it mid-edit: the user has
   * typed a base URL and a key but not saved them yet, and a GET could only
   * list models for the previous configuration. Anything omitted falls back to
   * the account's saved provider server-side, so an already-configured user can
   * refresh without retyping their key.
   *
   * `listable` is false for Anthropic and Gemini, which have no equivalent
   * listing in the shape the OpenAI SDK speaks; the panel keeps its free-text
   * box in that case rather than offering an empty menu. */
  providerModels(input?: {
    apiType?: string;
    baseUrl?: string;
    apiKey?: string;
  }): Promise<{ models: string[]; listable: boolean }> {
    return apiFetch("/api/agents/provider-models", {
      method: "POST",
      body: JSON.stringify(input || {}),
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
    prompts: Record<string, string>,
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
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/${coordParam(coord)}`,
      { method: "DELETE" },
    );
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
    coord: string,
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
    attachmentId: string,
  ): Promise<{ attachmentId: string; detached: boolean }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: "DELETE" },
    );
  },

  /** Set/clear the attachment's editable intent; null/empty restores the prompt source. */
  updateAttachmentIntent(
    projectId: string,
    attachmentId: string,
    intent: string | null,
  ): Promise<AgentAttachment> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: "PATCH", body: JSON.stringify({ intent }) },
    );
  },

  /** Manually rename the conversation title (memo dev/25): non-empty only;
   * a manual title always wins over auto-generation and survives clears. */
  updateAttachmentTitle(
    projectId: string,
    attachmentId: string,
    title: string,
  ): Promise<AgentAttachment> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: "PATCH", body: JSON.stringify({ title }) },
    );
  },

  /** Apply a pending review proposal (memo dev/41) — the only mutation path;
   * revision-safe (409 when the target drifted, marking the proposal stale). */
  applyProposal(
    projectId: string,
    attachmentId: string,
    proposalId: string,
  ): Promise<AgentApplyResult> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}/apply`,
      { method: "POST" },
    );
  },

  /** Apply ONE planned node from a pending plan proposal (dev/67-5,
   * Simulation Mode: create). The proposal stays pending until every ref is
   * applied or it is dismissed; edges are the connection stage's (67-8). */
  applyPlanNode(
    projectId: string,
    attachmentId: string,
    proposalId: string,
    ref: string,
  ): Promise<AgentPlanNodeApplyResult> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}/apply-node`,
      { method: "POST", body: JSON.stringify({ ref }) },
    );
  },

  /** Apply plan edges — the connection review stage (dev/67-8). Omitted
   * indices apply every not-yet-applied edge; refusals are per-edge and
   * named; `createdEdges` feeds the canvas bridge. */
  applyPlanEdges(
    projectId: string,
    attachmentId: string,
    proposalId: string,
    indices?: number[],
  ): Promise<AgentPlanEdgesResult> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}/apply-edges`,
      { method: "POST", body: JSON.stringify(indices ? { edges: indices } : {}) },
    );
  },

  /** Edit one planned node's goal before creation (dev/67-5): an audited
   * review-stage overlay — the pinned plan bytes stay immutable. */
  savePlanGoal(
    projectId: string,
    attachmentId: string,
    proposalId: string,
    ref: string,
    goal: string,
  ): Promise<{ proposalId: string; ref: string; goal: string; editedGoals: Record<string, string> }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}/plan-goals`,
      { method: "PATCH", body: JSON.stringify({ ref, goal }) },
    );
  },

  /** Dismiss a pending review proposal without applying it. */
  dismissProposal(
    projectId: string,
    attachmentId: string,
    proposalId: string,
  ): Promise<{ attachmentId: string; proposalId: string; status: AgentProposalStatus }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/proposals/${encodeURIComponent(proposalId)}`,
      { method: "DELETE" },
    );
  },

  /** The attachment's persisted chat transcript (its session history). */
  getSession(projectId: string, attachmentId: string): Promise<AgentSession> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/session`,
    );
  },

  /** Clear the transcript; the attachment and its session id are kept. */
  clearSession(projectId: string, attachmentId: string): Promise<AgentSession> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/session`,
      { method: "DELETE" },
    );
  },

  /** Run one turn of an attached agent and get its reply. */
  runAttachment(
    projectId: string,
    attachmentId: string,
    message: string,
    /** Ephemeral grounded context (memo dev/44) — composed fresh per send. */
    context?: string | null,
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
      { method: "POST", body: JSON.stringify(context ? { message, context } : { message }) },
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
    context?: string | null,
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
      },
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
    mode?: "write" | "propose",
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
      signal,
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
    signal?: AbortSignal,
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
      signal,
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
    signal?: AbortSignal,
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
      signal,
    );
    if (result === null) throw new Error("the run ended without a result");
    return result;
  },

  /** Cancel a running simulation (dev/67-9): stops at the next boundary. */
  cancelSimulate(
    projectId: string,
    attachmentId: string,
  ): Promise<{ attachmentId: string; cancelRequested: boolean }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/simulate/cancel`,
      { method: "POST" },
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
    signal?: AbortSignal,
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
      signal,
    );
    if (result === null) throw new Error("validation ended without a result");
    return result;
  },

  /** Cancel a running Solve (dev/63): new children stop dispatching at the
   * next node boundary; in-flight children finish and their results persist;
   * undispatched targets revert to pending. 409 when nothing is running. */
  cancelSolve(
    projectId: string,
    attachmentId: string,
  ): Promise<{ attachmentId: string; cancelRequested: boolean }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/solve/cancel`,
      { method: "POST" },
    );
  },
};
