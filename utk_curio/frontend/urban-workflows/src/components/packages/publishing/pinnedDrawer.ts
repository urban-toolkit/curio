/**
 * What the pin changes on a canvas drawer, the same for every drawer.
 *
 * Pinned, the drawer stays open while the canvas, the palette and the top bar
 * keep working beside it: the root carries `data-pinned="true"`, and the
 * shell's stylesheet (CatalogDrawerShell.module.css) then takes the pointer off
 * the root and the scrim, leaves it on the panel, and hides the scrim. So the
 * panel is a dialog that is not modal. Unpinned, the scrim covers the page and
 * the panel is a modal dialog, unless the drawer is never one (`modal: false`:
 * Define scenario, beside the canvas).
 *
 * Every drawer spreads `root` on its overlay root and `panel` on its panel, and
 * writes neither attribute itself.
 */
export function pinnedDrawer(pinned: boolean, { modal = true }: { modal?: boolean } = {}) {
  return {
    root: { "data-pinned": pinned ? ("true" as const) : undefined },
    panel: { "aria-modal": modal && !pinned ? ("true" as const) : undefined },
  };
}
