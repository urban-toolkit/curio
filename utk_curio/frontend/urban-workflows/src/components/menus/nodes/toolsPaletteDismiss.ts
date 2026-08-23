/** Marks dataset/package palette roots in ToolsMenu. */
export const TOOLS_PALETTE_DROPDOWN_ATTR = "data-curio-tools-palette-dropdown";

/**
 * Marks an OPEN palette panel. The panels are absolutely positioned beside the
 * left rail, so they fall outside the dock's own bounding rect - fitView needs
 * this hook to know how wide a strip the dock actually occludes
 * (see utils/fitViewWithMenuOffset.ts).
 */
export const TOOLS_PALETTE_PANEL_ATTR = "data-curio-tools-palette-panel";
