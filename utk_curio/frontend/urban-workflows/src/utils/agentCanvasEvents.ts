/**
 * Apply→canvas bridge events (memo dev/48 §3.3) — the typed mirror of
 * ``agentsPaletteEvents.ts`` for agent-applied graph mutations.
 *
 * The apply endpoint mutates the SAVED spec; these events carry the applied
 * mutation to the LIVE React Flow canvas in the same user action, so the next
 * canvas save re-posts the same state instead of silently clobbering it (the
 * dev/41 `node.content.write` clobber fix rides the same bridge). The apply
 * response is the only payload source — the bridge never re-derives it.
 */

export type AgentCreatedNode = {
  id: string;
  /** Canonical unversioned template id (``<packageId>/<templateId>``). */
  type: string;
  content: string;
  goal?: string;
  x: number;
  y: number;
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
      /** dev/52: a whole applied plan graph — bulk nodes + edges, then a fit. */
      kind: "graph-created";
      planId: string;
      nodes: AgentCreatedNode[];
      edges: Array<{ id: string; source: string; target: string }>;
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
        detail.kind === "graph-created")
    ) {
      listener(detail);
    }
  };
  window.addEventListener(AGENT_CANVAS_MUTATION_EVENT, handler);
  return () => window.removeEventListener(AGENT_CANVAS_MUTATION_EVENT, handler);
}
