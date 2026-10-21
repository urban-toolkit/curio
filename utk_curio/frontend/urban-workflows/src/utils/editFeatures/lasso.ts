/**
 * Lasso picking for the Interaction node's maps (`MapEditOverlay`,
 * `EditCanvas`): a freehand outline drawn on screen picks every feature with
 * a corner inside it, a point, a line's point or an area's corner alike.
 */
import type { SelectionId } from "../references/selectionTags";
import type { Geometry } from "./editFeatures";

type XY = [number, number];

/** A drag shorter than this, in screen pixels, is a click, not a lasso. */
export const LASSO_MIN_PIXELS = 6;

/** Whether *xy* is inside the closed outline *outline* (even-odd rule). */
export function insideOutline(xy: XY, outline: readonly XY[]): boolean {
  let inside = false;
  for (let i = 0, j = outline.length - 1; i < outline.length; j = i, i += 1) {
    const [xi, yi] = outline[i];
    const [xj, yj] = outline[j];
    if (yi > xy[1] !== yj > xy[1] && xy[0] < ((xj - xi) * (xy[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Every corner of *geometry*, of all its parts. */
function cornersOf(geometry: Geometry): XY[] {
  const out: XY[] = [];
  const walk = (value: any) => {
    if (!Array.isArray(value)) return;
    if (typeof value[0] === "number") out.push([value[0], value[1]]);
    else value.forEach(walk);
  };
  walk(geometry.coordinates);
  return out;
}

/**
 * The ids of *features* with a corner inside *outline*, a screen outline,
 * each feature's corners put on screen with *toScreen*.
 */
export function lassoPicks(
  features: readonly { id: SelectionId | null; geometry?: Geometry | null }[],
  outline: readonly XY[],
  toScreen: (xy: XY) => XY,
): SelectionId[] {
  if (outline.length < 3) return [];
  const picked: SelectionId[] = [];
  for (const f of features) {
    if (f.id === null || !f.geometry) continue;
    if (cornersOf(f.geometry).some((xy) => insideOutline(toScreen(xy), outline))) picked.push(f.id);
  }
  return picked;
}

/** How long *outline* is, in screen pixels: under `LASSO_MIN_PIXELS` it was a click. */
export function outlineLength(outline: readonly XY[]): number {
  let length = 0;
  for (let i = 1; i < outline.length; i += 1) length += Math.hypot(outline[i][0] - outline[i - 1][0], outline[i][1] - outline[i - 1][1]);
  return length;
}
