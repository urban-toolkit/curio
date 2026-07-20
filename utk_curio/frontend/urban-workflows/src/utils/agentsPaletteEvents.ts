/**
 * Lightweight refresh signal for the AGENTS tools-panel palette, mirroring the
 * dataset catalog's refresh-event convention. The catalog drawer dispatches this
 * after an install/uninstall so the palette re-reads the project lockfile without
 * a page reload; the palette subscribes.
 */
export const AGENTS_PALETTE_REFRESH_EVENT = "curio:agents-palette-refresh";

export function notifyAgentsPaletteRefresh(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AGENTS_PALETTE_REFRESH_EVENT));
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

/** The attach target for an agent drop. Mirrors the backend contract
 * (`app/agents/attachments.py`): a node/connection target carries the graph
 * element's id; canvas is the project-wide fallback. */
export type AgentDropTarget =
  | { kind: "node"; targetId: string }
  | { kind: "canvas" };

/**
 * Resolve which target an agent was dropped on. React Flow renders every node
 * wrapper as `.react-flow__node` carrying `data-id={node.id}`, so we walk up from
 * the drop's DOM target to that wrapper and read the id. Dropping anywhere off a
 * node (the pane, background) falls back to the canvas.
 */
export function resolveAgentDropTarget(eventTarget: EventTarget | null): AgentDropTarget {
  const el = eventTarget as Element | null;
  const nodeEl =
    el && typeof el.closest === "function" ? el.closest(".react-flow__node") : null;
  const targetId = nodeEl?.getAttribute("data-id");
  return targetId ? { kind: "node", targetId } : { kind: "canvas" };
}

/** Refresh signal for the attachment dock, dispatched after attach/detach so the
 * dock re-reads the project's attachments without a reload. */
export const AGENT_DOCK_REFRESH_EVENT = "curio:agent-dock-refresh";

export function notifyAgentDockRefresh(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AGENT_DOCK_REFRESH_EVENT));
  }
}
