/**
 * The three window events the agent surfaces speak through (memo dev/142, F1 —
 * formerly `utils/agentCanvasEvents.ts` and half of `utils/agentCatalogEvents.ts`).
 *
 * Canvas bridge events (memo dev/48 §3.3): the server writes the dataflow; these
 * carry the same mutation to the LIVE React Flow canvas, so the next canvas
 * save re-posts the same state instead of silently clobbering it. An agent's
 * change lands on the server through the dataflow's doc, so a canvas the doc
 * binds has it already: its mutation is marked `landed`, which only a canvas no
 * doc binds takes (a hosted guest's, a dataflow open without collaboration).
 * There, a change the agent landed in steps (a new node dragged in, a plan a
 * step at a time) plays each step as the room's tabs saw it: its drag, then
 * its mutation, one change after another.
 * The server's answer or stream is the only payload source: the bridge never
 * re-derives it. The catalog and dock refresh signals mirror the dataset
 * catalog's refresh-event convention: dispatched after an install/uninstall or
 * attach/detach so the palette and the dock re-read without a page reload.
 */

import type {
  AgentAppliedScenario,
  AgentDataPoolSetting,
  AgentNodeSettings,
  AgentPlanWidget,
  AgentSimpleVisSetting,
  AgentSpatialJoinSetting,
} from "./types/proposal";
import { agentsSeenThroughAwareness, holdAgentsOfChange } from "../../providers/collab/agentHolds";
import { playChangeDrag } from "../../providers/collab/agentDrags";

export type AgentCreatedNode = {
  id: string;
  /** Canonical unversioned template id (``<packageId>/<templateId>``). */
  type: string;
  content: string;
  goal?: string;
  x: number;
  y: number;
  /** dev/89: optional display title the apply persisted on the spec node. */
  title?: string;
  /** The name of the agent that wrote the node, which a node it adds with
   * code starts its Provenance history named after. Never saved on the node. */
  agent?: string;
  /** dev/89: canonical persisted appearance (normalized by the backend's
   * shared node-appearance utility) — carried into live ``data.appearance``
   * so the next canvas save round-trips it. #662: the same for the node's
   * widgets and, on a copy, its lineage (``data.widgets``, ``data.copiedFrom``),
   * for a Spatial Join its operation and output (``data.spatialJoin``), for a
   * Data Pool its modes (``data.dataPool``) and for a Simple View its image
   * column (``data.simpleVis``). */
  metadata?: {
    appearance?: { backgroundColor?: string };
    widgets?: AgentPlanWidget[];
    copiedFrom?: string[];
    spatialJoin?: AgentSpatialJoinSetting;
    dataPool?: AgentDataPoolSetting;
    simpleVis?: AgentSimpleVisSetting;
  };
};

/** A canvas mutation. `landed`: an agent's change (or its Undo), which the
 * server wrote into the dataflow's doc, so a canvas the doc binds holds it. */
export type AgentCanvasMutation = AgentCanvasMutationBody & { landed?: boolean };

type AgentCanvasMutationBody =
  | { kind: "node-created"; node: AgentCreatedNode }
  | {
      kind: "node-content-applied";
      nodeId: string;
      content: string;
      /** The name of the agent that wrote the content, which a node that
       * keeps a history of its changes names the entry after. */
      agent?: string;
    }
  | {
      /** An applied change of an existing node's settings: the live node
       * takes each through its own setter, as a pick in it would
       * (`utils/nodeSettingsWriters`). */
      kind: "node-settings-applied";
      nodeId: string;
      settings: AgentNodeSettings;
    }
  | {
      /** dev/52: a whole applied plan graph — bulk nodes + edges, then a
       * fit. dev/59: removals apply FIRST (the live graph drops victims
       * before inserts wire to survivors). */
      kind: "graph-created";
      planId: string;
      /** One step of the plan, as it landed, by its place in the plan: a
       *  canvas no doc binds takes a plan a step at a time. */
      step?: number;
      nodes: AgentCreatedNode[];
      edges: Array<{
        id: string;
        source: string;
        target: string;
        /** dev/67-3: explicit handles from the apply (input circles in_N). */
        sourceHandle?: string;
        targetHandle?: string;
        /** dev/112: `"Interaction"` for a Trill feedback edge (in/out both ends). */
        type?: string;
      }>;
      removedNodeIds?: string[];
      removedEdgeIds?: string[];
      /** #662: the scenarios the plan saved, joined to the canvas's. */
      scenarios?: AgentAppliedScenario[];
    }
  | {
      /** Nodes and connections that leave: a node an agent added, undone.
       * Idempotent per plan id. */
      kind: "plan-removals";
      planId: string;
      removedNodeIds: string[];
      removedEdgeIds: string[];
    }
  | {
      /** dev/89: an applied package draft — the promoted package's dirName
       * plus its requested nodes. The handler refreshes the package registry
       * BEFORE painting the nodes (registry-before-canvas: a descriptor must
       * resolve before UniversalNode renders it). Idempotent per artifact. */
      kind: "package-nodes-created";
      artifactDigest: string;
      packageDir: string;
      nodes: AgentCreatedNode[];
    };

export const AGENT_CANVAS_MUTATION_EVENT = "curio:agent-canvas-mutation";

export function notifyAgentCanvasMutation(mutation: AgentCanvasMutation): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<AgentCanvasMutation>(AGENT_CANVAS_MUTATION_EVENT, { detail: mutation }),
  );
}

const MUTATION_KINDS = new Set([
  "node-created",
  "node-content-applied",
  "node-settings-applied",
  "graph-created",
  "plan-removals",
  "package-nodes-created",
]);

function isMutation(value: unknown): value is AgentCanvasMutation {
  return Boolean(value) && typeof value === "object" && MUTATION_KINDS.has(String((value as { kind?: unknown }).kind));
}

/**
 * The canvas mutations of an agent's change that landed, or of its Undo, as a
 * run's `change` event, a blocking run's `changes` and the Undo answer carry
 * them (one mutation or a list): each dispatched marked `landed`, which a
 * canvas no doc binds takes. Anything else is skipped. Returns how many it
 * dispatched.
 */
export function notifyAgentChangesLanded(canvas: unknown): number {
  const mutations = (Array.isArray(canvas) ? canvas : [canvas]).filter(isMutation);
  for (const mutation of mutations) notifyAgentCanvasMutation({ ...mutation, landed: true });
  return mutations.length;
}

/** What a canvas no doc binds still has to play of the changes that landed,
 * in order: each a drag to play first, or none, then what lands. */
const toPlay: Array<{ dragged?: unknown; land: () => void }> = [];
let playing = false;

function playNext(): void {
  const next = toPlay.shift();
  if (!next) {
    playing = false;
    return;
  }
  playing = true;
  const land = () => {
    try {
      next.land();
    } finally {
      playNext();
    }
  };
  if (next.dragged) playChangeDrag(next.dragged, land);
  else land();
}

/** A run's stream event, when it says a change landed: its canvas mutations
 * go to the canvas bridge (`notifyAgentChangesLanded`). A canvas the dataflow's
 * doc binds saw the agent's drags and writes through the doc's awareness, and
 * has the change: it takes the whole change at once. On a canvas no doc binds,
 * the change plays as the room's tabs saw it, after the changes before it:
 * each of its `steps` in turn, the agent's drag first when the step had one
 * (`playChangeDrag`), then the step's mutation; and the nodes the agent wrote
 * show what it wrote just before they land, as its state in the room said it
 * (`writing`, `providers/collab/agentHolds`). True when it was one. */
export function bridgeLandedChangeEvent(name: string, payload: Record<string, unknown>): boolean {
  if (name !== "change") return false;
  if (agentsSeenThroughAwareness()) {
    holdAgentsOfChange(payload.writing);
    notifyAgentChangesLanded(payload.canvas);
    return true;
  }
  const steps = Array.isArray(payload.steps) ? (payload.steps as Array<Record<string, unknown>>) : null;
  if (steps && steps.length > 0) {
    steps.forEach((step, i) =>
      toPlay.push({
        dragged: step?.dragged,
        land: () => {
          if (i === 0) holdAgentsOfChange(payload.writing);
          notifyAgentChangesLanded(step?.canvas);
        },
      }),
    );
  } else {
    toPlay.push({
      land: () => {
        holdAgentsOfChange(payload.writing);
        notifyAgentChangesLanded(payload.canvas);
      },
    });
  }
  if (!playing) playNext();
  return true;
}

export function subscribeAgentCanvasMutations(
  listener: (mutation: AgentCanvasMutation) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<AgentCanvasMutation>).detail;
    if (isMutation(detail)) listener(detail);
  };
  window.addEventListener(AGENT_CANVAS_MUTATION_EVENT, handler);
  return () => window.removeEventListener(AGENT_CANVAS_MUTATION_EVENT, handler);
}

/**
 * Lightweight refresh signal for the AGENTS tools-panel palette, mirroring the
 * dataset catalog's refresh-event convention. The catalog drawer dispatches this
 * after an install/uninstall so the palette re-reads the project lockfile without
 * a page reload; the palette subscribes.
 */
export const AGENT_CATALOG_REFRESH_EVENT = "curio:agent-catalog-refresh";

export function notifyAgentCatalogRefresh(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AGENT_CATALOG_REFRESH_EVENT));
  }
}

/** Refresh signal for the attachment dock, dispatched after attach/detach so the
 * dock re-reads the project's attachments without a reload. */
export const AGENT_DOCK_REFRESH_EVENT = "curio:agent-dock-refresh";

export function notifyAgentDockRefresh(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AGENT_DOCK_REFRESH_EVENT));
  }
}
