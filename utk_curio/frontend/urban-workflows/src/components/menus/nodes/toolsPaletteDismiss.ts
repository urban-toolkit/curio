/** Marks dataset/package palette roots in ToolsMenu so they do not dismiss each other. */
export const TOOLS_PALETTE_DROPDOWN_ATTR = "data-curio-tools-palette-dropdown";

/** True when a palette should close for this document mousedown (outside click). */
export function isToolsPaletteDismissOutsideClick(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return true;
  if (target.closest(`[${TOOLS_PALETTE_DROPDOWN_ATTR}]`)) return false;
  if (target.closest('[data-curio-node-catalog-drawer="true"]')) return false;
  if (target.closest('[data-curio-package-palette-node-action="true"]')) return false;
  return true;
}
