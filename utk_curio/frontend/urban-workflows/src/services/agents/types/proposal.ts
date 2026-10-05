/**
 * Review-before-apply: proposal parts and statuses, dataflow plans, apply results, and the builder session (the plan's per-node ledger).
 *
 * Split out of `api/agentsApi.ts` (memo dev/142, F1); every shape keeps its name.
 */

import type { AgentSourceRef, AgentValidationAttempt } from "./evidence";

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
  /** #662 (plan proposals): scenario index → applied|refused, once any is. */
  scenarioStates?: Record<string, string>;
}

/** #662: a widget a planned or created node declares (`metadata.widgets`). */
export interface AgentPlanWidget {
  name: string;
  type: string;
  label?: string;
  default?: unknown;
  value?: unknown;
  options?: Record<string, unknown>;
}

/** #662: a scenario a plan saves, on the review card. */
export interface AgentPlanScenario {
  name: string;
  color: string;
  description?: string;
  /** Its nodes: plan refs, or ids of nodes already in the dataflow. */
  nodes: Array<{ ref: string; label: string }>;
  /** A duplicate: the scenario it copies, and the widget values its copies change. */
  duplicateOf?: string;
  values?: Record<string, Record<string, unknown>>;
}

/** #662: a scenario an apply saved, as `dataflow.scenarios` holds it. */
export interface AgentAppliedScenario {
  id: string;
  name: string;
  color: string;
  description?: string;
  nodes: string[];
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
  nodeProposals?: Record<string, string | { proposalId: string; attachmentId?: string | null }>;
}

/** dev/114: the proposal's source block — bounded plain data. */
export interface AgentProposalSource {
  kind: "catalog" | "external" | "user-path" | "synthetic" | "mixed" | string;
  label: string;
  refs: AgentSourceRef[];
}

export type AgentProposalStatus = "pending" | "applied" | "dismissed" | "superseded" | "stale";

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
  pins: {
    [key: string]: string | boolean | undefined;
    nodeType?: string;
    dirName?: string;
    executable?: boolean;
  };
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
    files: {
      added: string[];
      modified: string[];
      addedTotal: number;
      modifiedTotal: number;
      preservedTotal: number;
    };
    templates: {
      added: string[];
      modified: string[];
      addedTotal: number;
      modifiedTotal: number;
      preservedTotal: number;
    };
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
      /** #662: the widgets it declares, the scenario it is in, and for a
       * copy the ref of the node it copies. */
      widgets?: AgentPlanWidget[];
      scenario?: string;
      copyOf?: string;
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
    /** #662: the scenarios the plan saves, each with its nodes by name. */
    scenarios?: AgentPlanScenario[];
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
  /** dev/89: canonical persisted appearance (backend-normalized). #662: the
   * node's widgets, and for a copy the ids it descends from. */
  metadata?: { appearance?: { backgroundColor?: string }; widgets?: AgentPlanWidget[]; copiedFrom?: string[] };
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
      /** dev/67-3: explicit handles from the apply (input circles in_N). */
      sourceHandle?: string;
      targetHandle?: string;
      /** dev/112: `"Interaction"` for a feedback edge. */
      type?: string;
    }>;
    removedNodeIds?: string[];
    removedEdgeIds?: string[];
    /** #662: the scenarios the plan saved. */
    scenarios?: AgentAppliedScenario[];
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
  edgeResults?: Record<
    string,
    { status: string; reason?: string; fromLabel?: string; toLabel?: string }
  >;
  edgeStates?: Record<string, string>;
  /** #662: the scenarios this node completed, and which of the plan's are saved. */
  createdScenarios?: AgentAppliedScenario[];
  scenarioStates?: Record<string, string>;
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
