/**
 * Duplicate selection (#662), on the saved shape of a dataflow: the selected
 * nodes are copied with fresh ids, the edges between them are copied, and
 * every edge that enters the selection from outside is wired into the copy
 * too, so the copy reads the same context. Edges that leave the selection are
 * not copied: what reads the original keeps reading it.
 *
 * Each copy records where it came from at `metadata.copiedFrom`: the
 * original's own lineage, then the original. Two nodes pair when their ids
 * and lineages meet, which is how Compare Scenarios lines up levers.
 */

export interface SpecNode {
  id: string;
  x?: number;
  y?: number;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SpecEdge {
  id: string;
  source: string;
  target: string;
  type?: string;
  sourceHandle?: string;
  targetHandle?: string;
  [key: string]: unknown;
}

export interface Duplicate {
  nodes: SpecNode[];
  edges: SpecEdge[];
  /** Each original id to its copy's. */
  ids: Map<string, string>;
}

/** The ids in a saved `metadata.copiedFrom`, oldest first; anything else is dropped. */
export function lineageFromSpec(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.filter((id): id is string => typeof id === "string" && id.length > 0) : [];
}

/** The ids a spec node descends from, oldest first. */
export function lineageOf(node: { metadata?: Record<string, unknown> }): string[] {
  return lineageFromSpec(node.metadata?.copiedFrom);
}

const isInteraction = (edge: SpecEdge) => edge.type === "Interaction";

export function duplicateSelection(
  spec: { nodes: readonly SpecNode[]; edges: readonly SpecEdge[] },
  selected: readonly string[],
  options: { newId: () => string; offset: { x: number; y: number } },
): Duplicate {
  const wanted = new Set(selected);
  const originals = spec.nodes.filter((node) => wanted.has(node.id));
  const ids = new Map(originals.map((node) => [node.id, options.newId()]));

  const nodes = originals.map((node) => {
    const copy: SpecNode = JSON.parse(JSON.stringify(node));
    copy.id = ids.get(node.id)!;
    if (typeof node.x === "number") copy.x = node.x + options.offset.x;
    if (typeof node.y === "number") copy.y = node.y + options.offset.y;
    copy.metadata = { ...(copy.metadata ?? {}), copiedFrom: [...lineageOf(node), node.id] };
    // A copy is not a dashboard tile until someone pins it.
    delete copy.dashboardPinned;
    delete copy.dashboardX;
    delete copy.dashboardY;
    return copy;
  });

  const edges: SpecEdge[] = [];
  for (const edge of spec.edges) {
    const source = ids.get(edge.source);
    const target = ids.get(edge.target);
    if (!target) continue;
    // A link between two views outside the selection and in it is not data
    // the copy reads; one between two copied views is copied with them.
    if (!source && isInteraction(edge)) continue;
    const copy: SpecEdge = JSON.parse(JSON.stringify(edge));
    copy.id = options.newId();
    copy.source = source ?? edge.source;
    copy.target = target;
    // Always explicit: without one, a load reads the circle from the edge id.
    copy.targetHandle = edge.targetHandle ?? (isInteraction(edge) ? "in/out" : "in");
    edges.push(copy);
  }
  return { nodes, edges, ids };
}
