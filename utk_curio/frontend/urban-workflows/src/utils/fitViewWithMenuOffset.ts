import type { ReactFlowInstance, FitViewOptions, Node } from "reactflow";
import { getNodesBounds, getViewportForBounds } from "reactflow";

// fitView centers content in the full pane, but the palette dock
// (`#tools-palette-dock`) is a fixed overlay on the left — and with a panel open
// it occludes a wide strip. We compute the fitted viewport against only the
// *visible* width (pane minus the occluded strip) and shift it right past the
// dock in a SINGLE animated setViewport, so content is both correctly sized and
// centered in the area to the right of the open palette.
//
// Fitting against the full pane width and merely nudging the result right (the
// earlier approach) sized content for a viewport wider than the visible area —
// with a wide panel open, a framed node overflowed off the right edge. Sizing to
// the visible width is what actually makes the node fit on screen.
//
// (The very first approach — rf.fitView() then a second rf.setViewport — was
// also broken for animated fits: fitView starts an async transition and returns
// immediately, so the viewport read back was the pre-animation value and the
// instant setViewport cancelled the fit, shifting the canvas instead of framing.)

const FALLBACK_MIN_ZOOM = 0.05;
const FALLBACK_MAX_ZOOM = 2;
const DEFAULT_PADDING = 0.1;

export function fitViewWithMenuOffset(
    rf: ReactFlowInstance,
    options?: FitViewOptions,
): boolean {
    const requestedIds = (options?.nodes ?? [])
        .map((n: any) => n?.id)
        .filter((id: unknown): id is string => typeof id === "string");
    const allNodes = rf.getNodes();
    const targetNodes = requestedIds.length
        ? allNodes.filter((n) => requestedIds.includes(n.id))
        : allNodes;
    if (targetNodes.length === 0) return false;

    // React Flow populates `width`/`height` only after it measures each node in
    // the DOM. Loading a workflow can run this before measurement, when the
    // dimensions are still null — bounds would then collapse to a near-zero
    // point and getViewportForBounds would over-zoom to maxZoom on it. Report
    // failure so the caller's retry loop waits for measurement instead of
    // halting on a degenerate fit.
    const measured = (n: Node) =>
        typeof n.width === "number" && n.width > 0 &&
        typeof n.height === "number" && n.height > 0;
    if (!targetNodes.every(measured)) return false;

    const container = document.querySelector<HTMLElement>(".react-flow");
    const paneRect = container?.getBoundingClientRect();
    // No measurable pane (headless / tests / hidden): fall back to plain fitView so
    // focusing still works, just without the menu offset.
    if (!paneRect || paneRect.width === 0 || paneRect.height === 0) {
        return rf.fitView(options);
    }

    const padding = typeof options?.padding === "number" ? options.padding : DEFAULT_PADDING;
    const minZoom = options?.minZoom ?? FALLBACK_MIN_ZOOM;
    const maxZoom = options?.maxZoom ?? FALLBACK_MAX_ZOOM;

    // Width the dock occludes on the left (measured from the pane's left edge).
    // With a palette panel open this is wide, so it must shrink the width the fit
    // is computed against — otherwise content is sized for the full pane and
    // overflows the visible strip. Clamp so the visible width stays positive.
    const dock = document.getElementById("tools-palette-dock");
    let occluded = 0;
    if (dock) {
        const raw = dock.getBoundingClientRect().right - paneRect.left;
        if (raw > 0) occluded = Math.min(raw, paneRect.width - 1);
    }
    const visibleWidth = Math.max(1, paneRect.width - occluded);

    const bounds = getNodesBounds(targetNodes);
    const { x, y, zoom } = getViewportForBounds(
        bounds,
        visibleWidth,
        paneRect.height,
        minZoom,
        maxZoom,
        padding,
    );

    // getViewportForBounds centered the content within [0, visibleWidth]; shift it
    // right past the dock so it centers in the strip [occluded, paneRect.width].
    rf.setViewport(
        { x: x + occluded, y, zoom },
        options?.duration ? { duration: options.duration } : undefined,
    );
    return true;
}
