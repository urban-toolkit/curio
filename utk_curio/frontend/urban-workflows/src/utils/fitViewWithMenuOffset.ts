import type { ReactFlowInstance, FitViewOptions, Node } from "reactflow";
import { getNodesBounds, getViewportForBounds } from "reactflow";
import { TOOLS_PALETTE_PANEL_ATTR } from "../components/menus/nodes/toolsPaletteDismiss";
import { isDrawnHidden } from "./hiddenNodes";

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
// The menu bar is the same kind of overlay along the top: `position: fixed` over
// the pane, --curio-top-bar-height tall. Fitted against the full pane height, a dataflow whose
// height sets the zoom got about 60 px of top margin, and the top node's title
// bar sat under the bar (#493). So the height is measured the way the width is:
// the fit uses the pane below the bar and is shifted down by it. The dataflow
// title and its category chips hang below the bar, so they count too.
//
// (The very first approach — rf.fitView() then a second rf.setViewport — was
// also broken for animated fits: fitView starts an async transition and returns
// immediately, so the viewport read back was the pre-animation value and the
// instant setViewport cancelled the fit, shifting the canvas instead of framing.)

/** The attribute the top bar (GlobalPageHeader) carries; the canvas wears it. */
export const MENU_BAR_ATTR = "data-curio-menu-bar";

/** The attribute UpMenu puts on the dataflow title block under the bar. Its
 *  category chips hang below it, so the fit keeps the top node clear of both. */
export const CANVAS_TITLE_ATTR = "data-curio-canvas-title";

/** The lowest bottom edge of the overlays fixed along the top of the pane.
 *  The notebook view starts its column below the same edge. */
export function topOverlayBottom(): number | null {
    const overlays = [
        ...document.querySelectorAll<HTMLElement>(`[${MENU_BAR_ATTR}]`),
        ...document.querySelectorAll<HTMLElement>(
            `[${CANVAS_TITLE_ATTR}], [${CANVAS_TITLE_ATTR}] [data-curio-category-chips]`,
        ),
    ];
    if (overlays.length === 0) return null;
    return Math.max(...overlays.map((el) => el.getBoundingClientRect().bottom));
}

/** The right edge of the palette rail (`#tools-palette-dock`) without any
 *  open panel: the notebook view keeps its column clear of it. */
export function paletteRailRight(): number | null {
    const dock = document.getElementById("tools-palette-dock");
    return dock ? dock.getBoundingClientRect().right : null;
}

const FALLBACK_MIN_ZOOM = 0.05;
const FALLBACK_MAX_ZOOM = 2;
const DEFAULT_PADDING = 0.1;

export function fitViewWithMenuOffset(
    rf: ReactFlowInstance,
    /** `headroom`: room to keep in view above the nodes, in canvas units,
     *  for what is drawn there (the dashboard's scenario headers, #662). */
    options?: FitViewOptions & { headroom?: number },
): boolean {
    const requestedIds = (options?.nodes ?? [])
        .map((n: any) => n?.id)
        .filter((id: unknown): id is string => typeof id === "string");
    const allNodes = rf.getNodes();
    const requested = requestedIds.length
        ? allNodes.filter((n) => requestedIds.includes(n.id))
        : allNodes;
    if (requested.length === 0) return false;
    // A node drawn hidden (a collapsed scenario's member, #662) is never
    // measured, so waiting for its size would never end. Fit the others; when
    // every one is hidden, fit where they stand, which is where a collapsed
    // scenario's box sits.
    const shown = requested.filter((n) => !isDrawnHidden(n));
    const targetNodes = shown.length
        ? shown
        : requested.map((n) => ({ ...n, width: n.width || 1, height: n.height || 1 }));

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
    // The dock's own rect covers just the left rail; an open palette panel is
    // absolutely positioned beside it and so is NOT part of that rect. Take the
    // rightmost edge across the rail and any open panel.
    const dock = document.getElementById("tools-palette-dock");
    let occluded = 0;
    if (dock) {
        let right = dock.getBoundingClientRect().right;
        dock.querySelectorAll<HTMLElement>(`[${TOOLS_PALETTE_PANEL_ATTR}]`).forEach((panel) => {
            right = Math.max(right, panel.getBoundingClientRect().right);
        });
        const raw = right - paneRect.left;
        if (raw > 0) occluded = Math.min(raw, paneRect.width - 1);
    }
    const visibleWidth = Math.max(1, paneRect.width - occluded);

    // Height the menu bar, and the dataflow title with its category chips below
    // it, cover at the top of the pane, measured the same way.
    const overlayBottom = topOverlayBottom();
    let occludedTop = 0;
    if (overlayBottom !== null) {
        const raw = overlayBottom - paneRect.top;
        if (raw > 0) occludedTop = Math.min(raw, paneRect.height - 1);
    }
    const visibleHeight = Math.max(1, paneRect.height - occludedTop);

    const nodeBounds = getNodesBounds(targetNodes);
    const headroom = Math.max(0, options?.headroom ?? 0);
    const bounds = { ...nodeBounds, y: nodeBounds.y - headroom, height: nodeBounds.height + headroom };
    const { x, y, zoom } = getViewportForBounds(
        bounds,
        visibleWidth,
        visibleHeight,
        minZoom,
        maxZoom,
        padding,
    );

    // getViewportForBounds centered the content within the visible box at the
    // origin; shift it right past the dock and down past the bar so it centers
    // in [occluded, paneRect.width] x [occludedTop, paneRect.height].
    rf.setViewport(
        { x: x + occluded, y: y + occludedTop, zoom },
        options?.duration ? { duration: options.duration } : undefined,
    );
    return true;
}
