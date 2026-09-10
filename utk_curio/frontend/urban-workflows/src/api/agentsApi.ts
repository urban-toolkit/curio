import { apiFetch, getToken } from "../utils/authApi";
import { backendUrl } from "../utils/backendUrl";

const BACKEND_URL = backendUrl();

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
  /** dev/115 (DEC-073): the background job this server process holds for the
   * attachment — a Solve batch or a per-node Solve that outlives the request.
   * Null when none runs; the dock's running indicator and the chat panel's
   * re-attach derive from it. */
  liveJob?: AgentLiveJob | null;
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
  /** dev/115: `interrupted` — the server stopped while solving (DEC-021);
   * Retry starts a new execution linked to it, nothing is replayed. */
  phase: "idle" | "plan_review" | "simulating" | "applied" | "solving" | "ready" | "interrupted";
  /** dev/115: when the session was reconciled to `interrupted`, and the
   * execution that expired with the process. */
  interruptedAt?: number;
  interruptedExecutionId?: string;
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

/** dev/114: one grounded source reference on a proposal. */
export interface AgentSourceRef {
  kind: "catalog" | "external" | "user-path" | "synthetic" | "secret" | string;
  /** The literal the code uses: a path, a curio_dataset_path("<id>") call, or a URL. */
  value?: string;
  datasetId?: string;
  title?: string;
  format?: string;
  /** external only: the DEC-053 probe verdict the runtime recorded. */
  verification?: AgentDatasetCandidateRow["verification"];
  /** external only: "credential-gated" when the endpoint answered 401/403. */
  requirement?: string;
  /** external only (dev/116): a saved connection key is bound to this host. */
  hint?: string;
  /** secret only (dev/116): the connection key the code reaches by name. */
  name?: string;
  host?: string;
  delivery?: string;
}

/** dev/116: what a `source-missing` failure asks the user for.
 *  dev/126 adds `dataset-selection`: the node's source is with the user —
 *  its Dataset Finder holds candidates awaiting a selection. */
export interface AgentRemedy {
  kind: "connection-key" | "use-connection-key" | "dataset-selection" | string;
  host?: string;
  /** connection-key: a name the settings form can suggest. */
  suggestedName?: string;
  /** use-connection-key: the saved key the builder did not use. */
  name?: string;
  /** dataset-selection (dev/126): the chat to open, and the node it resolves. */
  attachmentId?: string;
  nodeId?: string;
}

/** dev/126: one confirmed candidate — identifiers ONLY. The server resolves
 *  the key against the rows it proposed itself, so a client can never
 *  introduce a source the runtime did not verify. */
export interface AgentDatasetPick {
  lane: "catalog" | "external";
  key: string;
}

/** dev/126: the recorded selection for a node. */
export interface AgentDatasetSelection {
  attachmentId: string;
  nodeId?: string;
  status: "resolved" | "awaiting-install" | "candidates-pending" | string;
  picks: AgentDatasetCandidateRow[];
}

/** dev/114: the proposal's source block — bounded plain data. */
export interface AgentProposalSource {
  kind: "catalog" | "external" | "user-path" | "synthetic" | "mixed" | string;
  label: string;
  refs: AgentSourceRef[];
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
  /**
   * Tool-specific revision-safety basis (dev/41 digest pins; dev/48
   * nodeType/coord/slug pins). `executable` (dev/119, DEC-076) is display,
   * not a pin: the roster's answer to whether the sandbox can run a
   * node.create's kind — the card never keeps its own list.
   */
  pins: { [key: string]: string | boolean | undefined; nodeType?: string; dirName?: string; executable?: boolean };
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
  /** dev/114 (DEC-072): how the proposed content's sources were grounded —
   * runtime-derived at mint (never model-claimed); display + provenance,
   * not a pin. Absent when the content opens no file and fetches no URL. */
  source?: AgentProposalSource;
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
      durationMs?: number;
    };
    /** dev/115: the attempt trail — one row per round the runtime executed
     * (or refused before executing): what ran, how it failed, what fixed it. */
    attempts?: AgentValidationAttempt[];
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
      /** dev/112 (DEC-069): present only for interaction (feedback) edges. */
      kind?: "data" | "interaction";
      fromLabel: string;
      toLabel: string;
    }>;
    /** dev/59 (DEC-049.2): removals reviewed by NAME — every victim listed
     * with a content flag; present only on destructive revisions. */
    removals?: Array<{ id: string; label: string; nodeType?: string; contentChars: number }>;
    removedEdgeCount?: number;
    cascadeCount?: number;
    /** dev/112: removed CONNECTIONS reviewed by name too (DEC-049.2 for edges). */
    removedEdges?: Array<{ id: string; fromLabel: string; toLabel: string; kind?: "interaction" }>;
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
      /** dev/112: `"Interaction"` for a feedback edge. */
      type?: string;
    }>;
    removedNodeIds?: string[];
    removedEdgeIds?: string[];
  };
  /** dev/126: the plan-node agents this apply attached (Node Builder on every
   * created node, Dataset Finder on every data-loading one) — and anything it
   * could not, with the reason. */
  attachedAgents?: AgentAttachedAgentRow[];
  skippedAgents?: AgentAttachedAgentRow[];
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
    type?: string; // dev/112
  }>;
  /** dev/71: the sweep's per-edge outcomes (index-keyed; refusals named). */
  edgeResults?: Record<string, { status: string; reason?: string; fromLabel?: string; toLabel?: string }>;
  edgeStates?: Record<string, string>;
  /** dev/71: the auto-attached Node Builder's attachment id (null = skipped). */
  attachedAgentId?: string | null;
  /** dev/126: every agent this apply gave the created node(s) — and anything
   * it could not, with the reason. Both apply paths report it. */
  attachedAgents?: AgentAttachedAgentRow[];
  skippedAgents?: AgentAttachedAgentRow[];
  builderSession?: AgentBuilderSession | null;
}

/** dev/126: one plan-node agent attachment an apply made (or could not). */
export interface AgentAttachedAgentRow {
  nodeId: string;
  agentId: string;
  attachmentId?: string | null;
  status: "attached" | "existing" | "skipped" | string;
  reason?: string;
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
      kind?: "interaction"; // dev/112
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
    type?: string; // dev/112
  }>;
  builderSession?: AgentBuilderSession | null;
}

/** dev/52 Solve response: per-node outcomes + live-canvas content payloads.
 * dev/63 adds the streamed batch's cancellation facts. */
/** dev/115: one round of the verified-content loop, as the cards render it. */
export interface AgentValidationAttempt {
  round: number;
  verdict: "pass" | "fail" | "infrastructure" | string;
  kind?: string;
  detail?: string;
  stderrTail?: string;
  outputDataType?: string;
  durationMs?: number;
  contentSha256?: string;
  /** "current content" (round 0 ran the node as it was) or "generated". */
  source?: string;
  /** dev/115 field fix: what the fetched endpoint actually answered when the round failed. */
  endpointEvidence?: string;
  /** dev/116: a credential decline's concrete remedy. */
  remedy?: AgentRemedy;
  /** dev/127: the candidate this round ran (failed rounds only). */
  code?: string;
  codeTruncated?: boolean;
  codeIsProse?: boolean;
  /** dev/118: ancestors whose earlier output stood in for a re-run. */
  reusedNodes?: string[];
  /** dev/118: a vanished reused artifact made the slice run whole once (not a round). */
  reuseRetried?: boolean;
}

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
  /** dev/115: the jobs re-attach stream is a GET (no body). */
  method: "POST" | "GET" = "POST",
): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (method === "POST") headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method,
    headers,
    ...(method === "POST" ? { body: JSON.stringify(body) } : {}),
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
   * Hybrid since #241, with both halves coming from the API. `source` is
   * `"live"` when the endpoint answered just now, or `"remembered"` when it
   * could not and Curio is replaying what it last reported - `rememberedAt`
   * says when that was, and `warning` why the live call did not happen.
   * `listable` means the endpoint itself answered; kept for older callers. */
  providerModels(input?: {
    apiType?: string;
    baseUrl?: string;
    apiKey?: string;
  }): Promise<{
    models: string[];
    listable: boolean;
    source?: "live" | "remembered";
    remembered?: string[];
    rememberedAt?: string | null;
    warning?: string | null;
  }> {
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

  /** dev/126: record the user's confirmed dataset selection for the node this
   * Dataset Finder is attached to. The picks carry identifiers only — the
   * server resolves them against the candidates it proposed. */
  recordDatasetSelection(
    projectId: string,
    attachmentId: string,
    picks: AgentDatasetPick[],
  ): Promise<AgentDatasetSelection> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/dataset-selection`,
      { method: "POST", body: JSON.stringify({ picks }) },
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
    signal?: AbortSignal,
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
      signal,
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
    signal?: AbortSignal,
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
      "GET",
    );
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
