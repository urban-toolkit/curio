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

/** The drag-data MIME key an agent palette row writes; the attach drop handler
 * reads the coordinate from it. Distinct from ``application/reactflow`` (node
 * creation) so the two never collide. */
export const AGENT_DRAG_MIME = "application/curio-agent";

/** Read the agent coordinate from a drag, or null when it is not an agent drag. */
export function readAgentDragCoord(dt: DataTransfer | null): string | null {
  if (!dt) return null;
  const coord = dt.getData(AGENT_DRAG_MIME);
  return coord || null;
}

/** Whether a drag carries an agent payload — detected via ``types`` so it works
 * during ``dragover`` (where ``getData`` returns "" in most browsers). The drop
 * handler must set ``dropEffect="copy"`` for these, matching the drag source's
 * ``effectAllowed="copy"``; a "move" effect makes the browser cancel the drop. */
export function hasAgentDrag(dt: DataTransfer | null): boolean {
  if (!dt) return false;
  return Array.from(dt.types || []).includes(AGENT_DRAG_MIME);
}

/** The attach target for an agent drop. Mirrors the backend contract
 * (`app/agents/attachments.py`): a node/connection target carries the graph
 * element's id; canvas is the project-wide fallback. */
export type AgentDropTarget =
  | { kind: "node"; targetId: string }
  | { kind: "connection"; targetId: string }
  | { kind: "canvas" };

/**
 * The edge under a drop point, or null.
 *
 * Hit-tested through the DOM rather than by re-deriving bezier geometry:
 * React Flow renders every edge with a wide invisible
 * `.react-flow__edge-interaction` path precisely so a pointer can land on a
 * curve. Reimplementing the curve maths here would be a second, worse source of
 * truth for where an edge *is*.
 *
 * Reading the id needs both attributes. In React Flow 11 only *nodes* get
 * `data-id`; the edge group is rendered with `data-testid="rf__edge-<id>"` and
 * no `data-id` at all (`@reactflow/core`, EdgeWrapper). Reading `data-id` alone
 * therefore returned null for every real edge, so an agent dropped on a
 * connection fell through to the canvas branch of `handleDrop` — and a
 * connection-only agent was then refused by the backend with "this agent
 * attaches to connection, node, not canvas". `data-id` is still preferred so
 * this keeps working if a later React Flow starts setting it.
 */
export function pickEdgeAtPoint(clientX: number, clientY: number): string | null {
  if (typeof document === "undefined" || !document.elementFromPoint) return null;
  const el = document.elementFromPoint(clientX, clientY);
  const edge = el?.closest?.(".react-flow__edge");
  if (!edge) return null;
  const direct = edge.getAttribute?.("data-id");
  if (direct) return direct;
  const testId = edge.getAttribute?.("data-testid");
  const fromTestId = testId?.startsWith("rf__edge-")
    ? testId.slice("rf__edge-".length)
    : null;
  return fromTestId || null;
}

export interface XYPoint {
  x: number;
  y: number;
}

/** Minimal node geometry (as returned by React Flow's ``getNodes()``). */
export interface NodeRect {
  id: string;
  position?: XYPoint;
  positionAbsolute?: XYPoint;
  width?: number | null;
  height?: number | null;
}

/**
 * Resolve which node an agent was dropped on by hit-testing the drop point (in
 * flow coordinates) against each node's bounding box, returning the id of the
 * topmost containing node or null for empty canvas. Coordinate hit-testing is
 * used instead of DOM ``closest('.react-flow__node')`` because React Flow's
 * pane/selection layer is often the actual drop-event target, so the DOM walk
 * would miss the node and everything would fall back to the canvas.
 */
export function pickNodeAtPoint(nodes: NodeRect[], point: XYPoint): string | null {
  // Iterate back-to-front: later nodes render on top, so the last match wins.
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const origin = n.positionAbsolute ?? n.position;
    if (!origin) continue;
    const w = n.width ?? 0;
    const h = n.height ?? 0;
    if (
      point.x >= origin.x &&
      point.x <= origin.x + w &&
      point.y >= origin.y &&
      point.y <= origin.y + h
    ) {
      return n.id;
    }
  }
  return null;
}

/** Refresh signal for the attachment dock, dispatched after attach/detach so the
 * dock re-reads the project's attachments without a reload. */
export const AGENT_DOCK_REFRESH_EVENT = "curio:agent-dock-refresh";

export function notifyAgentDockRefresh(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AGENT_DOCK_REFRESH_EVENT));
  }
}
