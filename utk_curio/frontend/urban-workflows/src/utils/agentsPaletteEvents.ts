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

/** Refresh signal for the attachment dock, dispatched after attach/detach so the
 * dock re-reads the project's attachments without a reload. */
export const AGENT_DOCK_REFRESH_EVENT = "curio:agent-dock-refresh";

export function notifyAgentDockRefresh(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AGENT_DOCK_REFRESH_EVENT));
  }
}
