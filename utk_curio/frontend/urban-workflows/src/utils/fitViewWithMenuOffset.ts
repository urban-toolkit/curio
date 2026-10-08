import type { ReactFlowInstance, ReactFlowState, FitViewOptions, Node, Viewport } from "reactflow";
import { getNodesBounds, getViewportForBounds } from "reactflow";
import { zoomIdentity } from "d3-zoom";
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

/** `headroom`: room to keep in view above the nodes, in canvas units, for
 *  what is drawn there (the dashboard's scenario headers, #662). */
type MenuOffsetFitOptions = FitViewOptions & { headroom?: number };

/** Where a fit puts the viewport, or why it cannot: none of the nodes it
 *  frames is on the canvas, one of them is not measured yet, or the pane has
 *  no size to fit against. */
type FitPlan = Viewport | "no nodes" | "unmeasured" | "no pane";

export function fitViewWithMenuOffset(rf: ReactFlowInstance, options?: MenuOffsetFitOptions): boolean {
    const plan = planFit(rf, options);
    // No measurable pane (headless / tests / hidden): fall back to plain fitView so
    // focusing still works, just without the menu offset.
    if (plan === "no pane") return rf.fitView(options);
    if (typeof plan === "string") return false;
    rf.setViewport(plan, options?.duration ? { duration: options.duration } : undefined);
    return true;
}

/** The part of React Flow's store that moves the viewport. */
type ZoomStore = { getState: () => Pick<ReactFlowState, "d3Zoom" | "d3Selection"> };

/**
 * `fitViewWithMenuOffset` without a duration, set at once: the fit the e2e
 * helpers ask for through `window.__curio_fitViewWithMenuOffset`. Returns the
 * viewport the canvas then shows, which is the current one when none of the
 * nodes is on the canvas, or null while one of them is not measured yet.
 *
 * React Flow 11's `setViewport` moves through a d3 transition even with no
 * duration, and a transition only advances on an animation frame, so the view
 * would change a frame or two later; a browser on a loaded GPU runner can go
 * tens of seconds without one. React Flow's own `fitView` sets a fit without a
 * duration through d3's zoom at once, and this does the same.
 */
export function fitViewWithMenuOffsetNow(
    rf: ReactFlowInstance,
    store: ZoomStore,
    options?: MenuOffsetFitOptions,
): Viewport | null {
    const plan = planFit(rf, options);
    if (plan === "no nodes") return rf.getViewport();
    if (plan === "unmeasured") return null;
    if (plan === "no pane") return rf.fitView({ ...options, duration: 0 }) ? rf.getViewport() : null;
    const { d3Zoom, d3Selection } = store.getState();
    if (!d3Zoom || !d3Selection) return null;
    d3Zoom.transform(d3Selection, zoomIdentity.translate(plan.x, plan.y).scale(plan.zoom));
    return plan;
}

function planFit(rf: ReactFlowInstance, options?: MenuOffsetFitOptions): FitPlan {
    const requestedIds = (options?.nodes ?? [])
        .map((n: any) => n?.id)
        .filter((id: unknown): id is string => typeof id === "string");
    const allNodes = rf.getNodes();
    const requested = requestedIds.length
        ? allNodes.filter((n) => requestedIds.includes(n.id))
        : allNodes;
    if (requested.length === 0) return "no nodes";
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
    if (!targetNodes.every(measured)) return "unmeasured";

    const container = document.querySelector<HTMLElement>(".react-flow");
    const paneRect = container?.getBoundingClientRect();
    if (!paneRect || paneRect.width === 0 || paneRect.height === 0) return "no pane";

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
    return { x: x + occluded, y: y + occludedTop, zoom };
}
