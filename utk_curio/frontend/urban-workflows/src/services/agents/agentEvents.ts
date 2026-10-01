/**
 * The three window events the agent surfaces speak through (memo dev/142, F1 —
 * formerly `utils/agentCanvasEvents.ts` and half of `utils/agentCatalogEvents.ts`).
 *
 * Apply→canvas bridge events (memo dev/48 §3.3): the apply endpoint mutates the
 * SAVED spec; these carry the applied mutation to the LIVE React Flow canvas in
 * the same user action, so the next canvas save re-posts the same state instead
 * of silently clobbering it (the dev/41 `node.content.write` clobber fix rides
 * the same bridge). The apply response is the only payload source — the bridge
 * never re-derives it. The catalog and dock refresh signals mirror the dataset
 * catalog's refresh-event convention: dispatched after an install/uninstall or
 * attach/detach so the palette and the dock re-read without a page reload.
 */

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
  /** dev/89: canonical persisted appearance (normalized by the backend's
   * shared node-appearance utility) — carried into live ``data.appearance``
   * so the next canvas save round-trips it. */
  metadata?: { appearance?: { backgroundColor?: string } };
};

export type AgentCanvasMutation =
  | {
      kind: "node-created";
      node: AgentCreatedNode;
      /**
       * Present when the apply also registered a NEW node type
       * (`node.template.create`): the package dirName to add to the
       * project-packages store before the registry refresh.
       */
      createdPackageDir?: string;
    }
  | { kind: "node-content-applied"; nodeId: string; content: string }
  | {
      /** dev/52: a whole applied plan graph — bulk nodes + edges, then a
       * fit. dev/59: removals apply FIRST (the live graph drops victims
       * before inserts wire to survivors). */
      kind: "graph-created";
      planId: string;
      nodes: AgentCreatedNode[];
      edges: Array<{
        id: string;
        source: string;
        target: string;
        /** dev/67-3: explicit handles from the apply (merge slots in_N). */
        sourceHandle?: string;
        targetHandle?: string;
        /** dev/112: `"Interaction"` for a Trill feedback edge (in/out both ends). */
        type?: string;
      }>;
      removedNodeIds?: string[];
      removedEdgeIds?: string[];
    }
  | {
      /** dev/67-8: connection-stage edges — inserted quietly (no fit, no
       * center); idempotent per batchId. */
      kind: "edges-created";
      batchId: string;
      edges: Array<{
        id: string;
        source: string;
        target: string;
        sourceHandle?: string;
        targetHandle?: string;
        /** dev/112: `"Interaction"` for a Trill feedback edge (in/out both ends). */
        type?: string;
      }>;
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

export function subscribeAgentCanvasMutations(
  listener: (mutation: AgentCanvasMutation) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<AgentCanvasMutation>).detail;
    if (
      detail &&
      (detail.kind === "node-created" ||
        detail.kind === "node-content-applied" ||
        detail.kind === "graph-created" ||
        detail.kind === "edges-created" ||
        detail.kind === "package-nodes-created")
    ) {
      listener(detail);
    }
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
