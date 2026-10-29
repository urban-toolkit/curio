/**
 * An agent's changes and the installs a person reviews: change and proposal parts and statuses, dataflow plans, apply and Undo results, and the builder session (the plan's per-node ledger).
 *
 * Split out of `api/agentsApi.ts` (memo dev/142, F1); every shape keeps its name.
 */

import type { AgentCanvasMutation } from "../agentEvents";
import type { AgentSourceRef, AgentValidationAttempt } from "./evidence";

/** The activeProposal mirror row (dev/41): an install a person reviews; and
 * `planProposal`, the plan the agent landed. */
export interface AgentProposalSummary {
  proposalId: string;
  tool: string;
  nodeId: string;
  summary: string;
  status: AgentProposalStatus;
  /** A landed plan: the refs it placed. */
  appliedRefs?: string[];
  /** A landed plan: ref → the node it placed. */
  nodeIds?: Record<string, string>;
  /** #662 (plans): scenario index → applied|refused, once any is. */
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

/** A Spatial Join's operation and output, as a planned or created one sets
 * them (`metadata.spatialJoin`). */
export interface AgentSpatialJoinSetting {
  predicate?: string;
  output?: "pairs" | "counts";
}

/** A Data Pool's conflict modes, as a planned or created one sets them
 * (`metadata.dataPool`): each a ResolutionType other than OVERWRITE. */
export interface AgentDataPoolSetting {
  insideChart?: string;
  betweenCharts?: string;
}

/** A Simple View's image column, as a planned or created one sets it
 * (`metadata.simpleVis`). */
export interface AgentSimpleVisSetting {
  imageColumn?: string;
}

/** A change of an existing node's settings (`node.settings.write`), by the
 * key the node keeps each at: each key a setting gives is picked as the
 * node's select picks it (OVERWRITE among a pool's modes), a key it leaves
 * out stays, and a Simple View's setting without a column picks every image
 * column; widget values are by widget name. */
export interface AgentNodeSettings {
  dataPool?: AgentDataPoolSetting;
  simpleVis?: AgentSimpleVisSetting;
  spatialJoin?: AgentSpatialJoinSetting;
  widgets?: Record<string, unknown>;
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
  phase: "idle" | "applied" | "solving" | "ready" | "interrupted";
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
  /** dev/67-9: the ref the driver is working on, while running. */
  currentRef?: string;
  /** dev/67-9: why the sequence paused — a plain reason with a next action. */
  pauseReason?: { kind: string; ref?: string; message: string };
  /** ref → the change its validated code landed as, and the attachment
   * whose chat holds it (dev/72: the node's own agent). */
  nodeChanges?: Record<string, { changeId: string; attachmentId?: string | null }>;
}

/** dev/114: the proposal's source block — bounded plain data. */
export interface AgentProposalSource {
  kind: "catalog" | "external" | "user-path" | "synthetic" | "mixed" | string;
  label: string;
  refs: AgentSourceRef[];
}

export type AgentProposalStatus = "pending" | "applied" | "dismissed" | "superseded" | "stale";

/**
 * An install a person reviews (memo dev/41): runtime-minted when a granted
 * install tool is requested. Only the authenticated apply endpoint executes
 * it; the part is the transcript's display record of the outcome.
 */
export interface AgentProposalPart {
  type: "proposal";
  proposalId: string;
  /** "package.install" | "package.draft.apply" | "dataset.install" | "discovery.acquire" | "project.install" | future kinds. */
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
  /** node.settings.write: each change, one line apiece, in its node's own
   * words, such as "Conflict between visualizations: Merge (AND)". */
  settingLines?: string[];
  /** package.draft.apply, when the draft adds node types: the closest existing
   * templates the model considered and why each is inadequate. The user judges it. */
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
       * copy the ref of the node it copies. A Spatial Join's operation and
       * output, a Data Pool's modes, a Simple View's image column. */
      widgets?: AgentPlanWidget[];
      scenario?: string;
      copyOf?: string;
      spatialJoin?: AgentSpatialJoinSetting;
      dataPool?: AgentDataPoolSetting;
      simpleVis?: AgentSimpleVisSetting;
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
     * with a content flag; present only on destructive revisions. `pinned`
     * only on a dashboard tile, which its removal takes off the dashboard. */
    removals?: Array<{ id: string; label: string; nodeType?: string; contentChars: number; pinned?: boolean }>;
    removedEdgeCount?: number;
    cascadeCount?: number;
    /** dev/112: removed CONNECTIONS reviewed by name too (DEC-049.2 for edges). */
    removedEdges?: Array<{ id: string; fromLabel: string; toLabel: string; kind?: "interaction" }>;
    /** #662: the scenarios the plan saves, each with its nodes by name. */
    scenarios?: AgentPlanScenario[];
  };
}

/** The kinds of an agent's change: a node's code, its settings, a new node,
 * a plan. Undo works by kind. */
export type AgentChangeKind = "content" | "settings" | "node" | "plan";

export type AgentChangeStatus = "applied" | "undone";

/**
 * A change an agent made to the dataflow, landed at once as a person's edit
 * lands (`proposals/changes.py`): its card in the chat says what it did and
 * offers its Undo. The display fields are its mint's: a node's code as the
 * preview, a settings change's lines, a plan's nodes, removals and scenarios.
 */
export interface AgentChangePart
  extends Omit<AgentProposalPart, "type" | "proposalId" | "pins" | "status" | "tool"> {
  type: "change";
  changeId: string;
  /** The tool that made it: "node.content.write" | "node.settings.write" | "node.create" | "dataflow.plan.write". */
  tool: string;
  kind: AgentChangeKind | string;
  status: AgentChangeStatus | string;
  /** What it did, a line each: the node it wrote, the settings it set, a plan's counts. */
  lines: string[];
  nodeId?: string;
  /** A plan's id: its rows read the attachment's ledger by it. */
  planId?: string;
  /** A new node's kind, and the roster's answer to whether the sandbox can
   * run it (dev/119, DEC-076): display only. */
  nodeType?: string;
  executable?: boolean;
}

/** A change that landed, as a run's `change` event and a blocking run's
 * `changes` carry it: a canvas no doc binds takes `canvas`. */
export interface AgentLandedChange {
  changeId: string;
  attachmentId: string | null;
  tool: string;
  canvas: AgentCanvasMutation | AgentCanvasMutation[];
}

/** The Undo endpoint's answer: the change's new status and the canvas
 * mutations a canvas no doc binds takes. */
export interface AgentUndoResult {
  attachmentId: string;
  changeId: string;
  status: AgentChangeStatus;
  canvas: AgentCanvasMutation[];
}

/** dev/52 DR-1: the model-emitted typed plan part (informational until the
 * runtime lands the plan from it). */
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
  /** node.create and package.draft.apply: the name of the agent that wrote
   * the node, which its Provenance history starts named after. The spec node
   * carries none. */
  agent?: string;
  /** dev/89: canonical persisted appearance (backend-normalized). #662: the
   * node's widgets, and for a copy the ids it descends from. A Spatial
   * Join's operation and output, a Data Pool's modes, a Simple View's image
   * column. */
  metadata?: {
    appearance?: { backgroundColor?: string };
    widgets?: AgentPlanWidget[];
    copiedFrom?: string[];
    spatialJoin?: AgentSpatialJoinSetting;
    dataPool?: AgentDataPoolSetting;
    simpleVis?: AgentSimpleVisSetting;
  };
}

/** Apply-endpoint response: an install a person reviewed (dev/41 base + the
 * dev/89 bridge payload). */
export interface AgentApplyResult {
  attachmentId: string;
  proposalId: string;
  status: AgentProposalStatus;
  mutationApplied?: boolean;
  /** project.install: the installed agent coordinate. */
  installedCoord?: string;
  /** dataset.install: the installed dataset. */
  installedDataset?: { id: string; name: string };
  /** package.install / package.draft.apply: the installed package. */
  installedPackage?: { dirName: string; name: string; replaced?: boolean };
  /** package.draft.apply (dev/89): the requested nodes inserted after the
   * reviewed install; package.install: the notes it placed. Painted only
   * after the registry refresh. */
  createdNodes?: AgentCreatedNodePayload[];
  /** package.draft.apply (dev/89), package.install: the frontend must refresh
   * the package/behavior/template registries BEFORE painting createdNodes. */
  requiresRegistryRefresh?: boolean;
}
