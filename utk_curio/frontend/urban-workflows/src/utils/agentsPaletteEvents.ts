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

/** The drag-data MIME key an agent palette row writes; the (future) attach drop
 * handler reads the coordinate from it. Distinct from ``application/reactflow``
 * (node creation) so the two never collide. */
export const AGENT_DRAG_MIME = "application/curio-agent";
