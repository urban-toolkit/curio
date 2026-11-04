/** Marks dataset/package palette roots in ToolsMenu. */
export const TOOLS_PALETTE_DROPDOWN_ATTR = "data-curio-tools-palette-dropdown";

/**
 * Marks an OPEN palette panel. The panels are absolutely positioned beside the
 * left rail, so they fall outside the dock's own bounding rect - fitView needs
 * this hook to know how wide a strip the dock actually occludes
 * (see utils/fitViewWithMenuOffset.ts).
 */
export const TOOLS_PALETTE_PANEL_ATTR = "data-curio-tools-palette-panel";

/** The tool rail's palettes, as ToolsMenu names the one that is open. */
export const RAIL_PALETTES = ["builtin", "packages", "datasets", "agents", "models"] as const;
export type RailPalette = (typeof RAIL_PALETTES)[number];

/**
 * The DOM id of a rail palette's root, which its dropdown sets
 * (`builtin-palette`, `models-palette`, ...). The root is as tall as the
 * palette's button: its panel opens beside the rail, out of the root's box.
 */
export function railPaletteRootId(palette: string): string {
    return `${palette}-palette`;
}

/**
 * Name what a drag source carries: a tile or a row of a rail palette, or a
 * card in a catalog drawer. `data-palette` is its palette, the one of its
 * catalog for a drawer's card, and `data-palette-item` its item: a node type, a
 * dataset or group id, or a model's package id. A package's card lists its
 * nodes' types, separated by spaces. An agent's drag of an item starts at the
 * element that names it (`providers/collab/agentDrags.ts`).
 */
export const PALETTE_ATTR = "data-palette";
export const PALETTE_ITEM_ATTR = "data-palette-item";

/** The attributes of a drag source of *items* in *palette*. */
export function paletteItemAttrs(palette: RailPalette, items: string | readonly string[]): Record<string, string> {
    return {
        [PALETTE_ATTR]: palette,
        [PALETTE_ITEM_ATTR]: typeof items === "string" ? items : items.join(" "),
    };
}
