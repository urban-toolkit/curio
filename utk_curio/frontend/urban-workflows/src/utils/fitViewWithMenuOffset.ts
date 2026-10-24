import type { ReactFlowInstance, ReactFlowState, FitViewOptions, Node, Rect, Viewport } from "reactflow";
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

/** The attribute a notice laid over the top of the pane wears, as a
 *  dashboard's notice to its visitors does: a tile under it could not be
 *  reached, so the fit keeps the top node below it too. */
export const TOP_NOTICE_ATTR = "data-curio-top-notice";

/** The lowest bottom edge of the overlays fixed along the top of the pane.
 *  The notebook view starts its column below the same edge. */
export function topOverlayBottom(): number | null {
    const overlays = [
        ...document.querySelectorAll<HTMLElement>(`[${MENU_BAR_ATTR}]`),
        ...document.querySelectorAll<HTMLElement>(
            `[${CANVAS_TITLE_ATTR}], [${CANVAS_TITLE_ATTR}] [data-curio-category-chips]`,
        ),
        ...document.querySelectorAll<HTMLElement>(`[${TOP_NOTICE_ATTR}]`),
    ];
    if (overlays.length === 0) return null;
    return Math.max(...overlays.map((el) => el.getBoundingClientRect().bottom));
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

/**
 * `fitViewWithMenuOffset` for a rectangle of the canvas, in its units, rather
 * than for nodes: for what is drawn beside React Flow and is not in its store,
 * such as a collapsed scenario's box (#769).
 */
export function fitBoundsWithMenuOffset(rf: ReactFlowInstance, bounds: Rect, options?: MenuOffsetFitOptions): boolean {
    const plan = planBoundsFit(bounds, options);
    if (plan === "no pane") {
        rf.fitBounds(bounds, { padding: options?.padding, duration: options?.duration });
        return true;
    }
    rf.setViewport(plan, options?.duration ? { duration: options.duration } : undefined);
    return true;
}

/** Whether *bounds* (canvas units) lie wholly in the part of the pane the
 *  overlays leave in sight, at the view the canvas shows now. */
export function boundsInSight(rf: ReactFlowInstance, bounds: Rect): boolean {
    const sight = paneInSight();
    if (!sight) return false;
    const { x, y, zoom } = rf.getViewport();
    const left = bounds.x * zoom + x;
    const top = bounds.y * zoom + y;
    return left >= sight.left && top >= sight.top &&
        left + bounds.width * zoom <= sight.left + sight.width &&
        top + bounds.height * zoom <= sight.top + sight.height;
}

/** The part of React Flow's store that moves the viewport (d3's zoom) and
 *  measures nodes (the canvas's element, and what its ResizeObserver calls). */
type ZoomStore = {
    getState: () => Pick<ReactFlowState, "d3Zoom" | "d3Selection" | "domNode" | "updateNodeDimensions">;
};

type NodeDimensionUpdate = Parameters<ReactFlowState["updateNodeDimensions"]>[0][number];

/** The part of React Flow's store that sets the viewport: d3's zoom. */
type ViewportStore = { getState: () => Pick<ReactFlowState, "d3Zoom" | "d3Selection"> };

/**
 * Set the canvas to *viewport* at once, through d3's zoom, as React Flow's own
 * `fitView` does without a duration. Returns false, setting nothing, while
 * React Flow's zoom is not up yet.
 *
 * React Flow 11's `setViewport` moves through a d3 transition even with no
 * duration, and a transition only advances on an animation frame, so the view
 * would change a frame or two later; a browser on a loaded runner can go
 * seconds without one. Set at once, the view also stops every move still
 * waiting for its frame on the canvas (d3 interrupts the pane's transitions),
 * so none of them lands over it later.
 */
export function setViewportNow(store: ViewportStore, viewport: Viewport): boolean {
    const { d3Zoom, d3Selection } = store.getState();
    if (!d3Zoom || !d3Selection) return false;
    d3Zoom.transform(d3Selection, zoomIdentity.translate(viewport.x, viewport.y).scale(viewport.zoom));
    return true;
}

/**
 * `fitViewWithMenuOffset` without a duration, set at once (`setViewportNow`):
 * the fit the e2e helpers ask for through `window.__curio_fitViewWithMenuOffset`.
 * Returns the viewport the canvas then shows, which is the current one when
 * none of the nodes is on the canvas, or null while one of them has no size to
 * fit. A browser on a loaded GPU runner can go tens of seconds without an
 * animation frame, which React Flow's `setViewport` would wait for.
 *
 * A node React Flow has not measured yet is measured here, from its element
 * (`measureNodesNow`), for the same reason.
 */
export function fitViewWithMenuOffsetNow(
    rf: ReactFlowInstance,
    store: ZoomStore,
    options?: MenuOffsetFitOptions,
): Viewport | null {
    let plan = planFit(rf, options);
    if (plan === "unmeasured" && measureNodesNow(rf, store, options)) plan = planFit(rf, options);
    if (plan === "no nodes") return rf.getViewport();
    if (plan === "unmeasured") return null;
    if (plan === "no pane") return rf.fitView({ ...options, duration: 0 }) ? rf.getViewport() : null;
    return setViewportNow(store, plan) ? plan : null;
}

/** The nodes a fit frames: those its options name, or every node. */
function requestedNodes(rf: ReactFlowInstance, options?: MenuOffsetFitOptions): Node[] {
    const requestedIds = (options?.nodes ?? [])
        .map((n: any) => n?.id)
        .filter((id: unknown): id is string => typeof id === "string");
    const allNodes = rf.getNodes();
    return requestedIds.length
        ? allNodes.filter((n) => requestedIds.includes(n.id))
        : allNodes;
}

/** Whether React Flow has measured *n*. */
const isMeasured = (n: Node) =>
    typeof n.width === "number" && n.width > 0 &&
    typeof n.height === "number" && n.height > 0;

function planFit(rf: ReactFlowInstance, options?: MenuOffsetFitOptions): FitPlan {
    const requested = requestedNodes(rf, options);
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
    if (!targetNodes.every(isMeasured)) return "unmeasured";

    return planBoundsFit(getNodesBounds(targetNodes), options);
}

/**
 * Measure the nodes a fit frames that React Flow has not measured yet, each
 * from its element, through React Flow's own `updateNodeDimensions`, which
 * reads the element's size at once. Returns whether it measured any.
 *
 * React Flow measures a node it has just drawn only in its ResizeObserver's
 * callback, which the browser runs only when it draws a frame. A freshly
 * launched Chrome on a GPU runner that several test jobs shared drew none for
 * more than 10 s (#1012), so a fit waiting for that callback could not be set.
 * A node drawn hidden has no size to read; the fit leaves it out.
 */
function measureNodesNow(rf: ReactFlowInstance, store: ZoomStore, options?: MenuOffsetFitOptions): boolean {
    const { domNode, updateNodeDimensions } = store.getState();
    if (!domNode || typeof updateNodeDimensions !== "function") return false;
    const elements = new Map<string, HTMLDivElement>();
    domNode.querySelectorAll<HTMLDivElement>(".react-flow__node").forEach((element) => {
        const id = element.getAttribute("data-id");
        if (id !== null) elements.set(id, element);
    });
    const updates: NodeDimensionUpdate[] = [];
    requestedNodes(rf, options).forEach((node) => {
        const nodeElement = elements.get(node.id);
        if (nodeElement && !isDrawnHidden(node) && !isMeasured(node)) {
            updates.push({ id: node.id, nodeElement, forceUpdate: true });
        }
    });
    if (updates.length === 0) return false;
    updateNodeDimensions(updates);
    return true;
}

/** Where a fit of *nodeBounds* (canvas units) puts the viewport, or "no pane"
 *  when the pane has no size to fit against. */
function planBoundsFit(nodeBounds: Rect, options?: MenuOffsetFitOptions): Viewport | "no pane" {
    const sight = paneInSight();
    if (!sight) return "no pane";

    const padding = typeof options?.padding === "number" ? options.padding : DEFAULT_PADDING;
    const minZoom = options?.minZoom ?? FALLBACK_MIN_ZOOM;
    const maxZoom = options?.maxZoom ?? FALLBACK_MAX_ZOOM;

    const headroom = Math.max(0, options?.headroom ?? 0);
    const bounds = { ...nodeBounds, y: nodeBounds.y - headroom, height: nodeBounds.height + headroom };
    const { x, y, zoom } = getViewportForBounds(
        bounds,
        sight.width,
        sight.height,
        minZoom,
        maxZoom,
        padding,
    );

    // getViewportForBounds centered the content within the visible box at the
    // origin; shift it right past the dock and down past the bar so it centers
    // in the part of the pane in sight.
    return { x: x + sight.left, y: y + sight.top, zoom };
}

/** The part of the pane the overlays leave in sight: its offset from the
 *  pane's top left corner and its size, in screen pixels. */
type PaneInSight = { left: number; top: number; width: number; height: number };

/** The part of the pane in sight, or null when the pane has no size. */
function paneInSight(): PaneInSight | null {
    const container = document.querySelector<HTMLElement>(".react-flow");
    const paneRect = container?.getBoundingClientRect();
    if (!paneRect || paneRect.width === 0 || paneRect.height === 0) return null;

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

    return { left: occluded, top: occludedTop, width: visibleWidth, height: visibleHeight };
}
