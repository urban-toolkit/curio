import type { CSSProperties } from "react";

/**
 * Marks the edge a palette-agent drag is currently over, for tests and e2e to
 * select on. Asserting on a computed `stroke` string would pin the colour as
 * well as the behaviour; this pins only the claim.
 */
export const EDGE_DROP_HOVER_ATTR = "data-curio-drop-hover";

/** Semantic token, not a literal: the same blue every focus affordance uses. */
export const EDGE_DROP_HOVER_STROKE = "var(--curio-focus-ring)";

/** Between MainCanvas.css's resting 3 and its :hover 9, so it reads as its own state. */
export const EDGE_DROP_HOVER_WIDTH = 7;

/**
 * The inline style for an edge path, highlighted or not (#296).
 *
 * `BaseEdge` takes no `className` (its props are style / markers /
 * interactionWidth / the label options), so an edge's appearance can only be
 * driven inline - which is what both edge components already do.
 *
 * **The resting branch deliberately emits no `strokeWidth`.** Emitting one
 * unconditionally would override `path.react-flow__edge-path` in
 * `MainCanvas.css` - and its `:hover` companion - for every edge on every
 * canvas, which is a visible change to every committed screenshot baseline. The
 * highlighted branch is the only one that sets it, so the default and the
 * pointer-hover rule keep working untouched.
 */
export function edgeDropHighlightStyle(
  baseStroke: string,
  hovered: boolean,
): CSSProperties {
  return hovered
    ? { stroke: EDGE_DROP_HOVER_STROKE, strokeWidth: EDGE_DROP_HOVER_WIDTH }
    : { stroke: baseStroke };
}
