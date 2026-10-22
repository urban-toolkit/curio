/**
 * Where the one Curio tooltip goes, and how large it may grow (TooltipLayer).
 *
 * Pure: the target's box on screen, the tooltip's size and the window's in,
 * a place out. Above the target, centered on it, TOOLTIP_GAP px away; below
 * it when there is no room above; shifted to stay TOOLTIP_MARGIN px inside the
 * window. A tool rail palette row opens it to the right. A chart's data
 * tooltip goes where the pointer is, by the same rules, the pointer standing
 * for a target of no size.
 *
 * The tooltip is drawn on document.body from these on-screen boxes, so the
 * canvas's zoom never scales it.
 */

/** The gap between a tooltip and its target, in px. */
export const TOOLTIP_GAP = 6;
/** How far a tooltip stays inside the window's edges, in px. */
export const TOOLTIP_MARGIN = 8;
/** The widest plain text grows before it wraps, in px. */
export const TOOLTIP_TEXT_MAX_WIDTH = 320;
/** The largest a preview grows, in px; it is cut to fit, never scrolled. */
export const TOOLTIP_PREVIEW_MAX_WIDTH = 480;
export const TOOLTIP_PREVIEW_MAX_HEIGHT = 360;

/** Which side of its target a tooltip asks for: `data-tooltip-side`. */
export type TooltipSide = "top" | "right" | "pointer";
/** Where it went. */
export type TooltipPlacement = "top" | "bottom" | "right";

/** A box on screen, as getBoundingClientRect gives one. */
export interface TooltipBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface TooltipSize {
  width: number;
  height: number;
}

/** *start*, moved if need be so that it and *length* after it stay TOOLTIP_MARGIN inside 0 to *limit*. */
function inside(start: number, length: number, limit: number): number {
  return Math.max(TOOLTIP_MARGIN, Math.min(start, limit - TOOLTIP_MARGIN - length));
}

/** Where a tooltip of *size* goes for *target*, in the window *viewport*. */
export function placeTooltip({
  target,
  size,
  viewport,
  side = "top",
  pointer = null,
}: {
  target: TooltipBox;
  size: TooltipSize;
  viewport: TooltipSize;
  side?: TooltipSide;
  pointer?: { x: number; y: number } | null;
}): { left: number; top: number; placement: TooltipPlacement } {
  if (side === "right") {
    return {
      left: target.left + target.width + TOOLTIP_GAP,
      top: inside(target.top + target.height / 2 - size.height / 2, size.height, viewport.height),
      placement: "right",
    };
  }
  const anchor = side === "pointer" && pointer ? { left: pointer.x, top: pointer.y, width: 0, height: 0 } : target;
  const left = inside(anchor.left + anchor.width / 2 - size.width / 2, size.width, viewport.width);
  const above = anchor.top - TOOLTIP_GAP - size.height;
  if (above >= TOOLTIP_MARGIN) return { left, top: above, placement: "top" };
  return { left, top: anchor.top + anchor.height + TOOLTIP_GAP, placement: "bottom" };
}

/**
 * How large a tooltip may grow in *viewport*: plain text 320 px wide, a
 * preview 480 x 360 px, and neither wider than the window less its margins.
 */
export function tooltipMaxSize(
  kind: "text" | "preview",
  viewport: TooltipSize,
): { maxWidth: number; maxHeight?: number } {
  const room = Math.max(0, viewport.width - 2 * TOOLTIP_MARGIN);
  if (kind === "text") return { maxWidth: Math.min(TOOLTIP_TEXT_MAX_WIDTH, room) };
  return {
    maxWidth: Math.min(TOOLTIP_PREVIEW_MAX_WIDTH, room),
    maxHeight: Math.min(TOOLTIP_PREVIEW_MAX_HEIGHT, Math.max(0, viewport.height - 2 * TOOLTIP_MARGIN)),
  };
}
