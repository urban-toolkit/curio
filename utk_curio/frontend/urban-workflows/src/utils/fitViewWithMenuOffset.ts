import type { ReactFlowInstance, FitViewOptions } from "reactflow";
import { getRectOfNodes, getViewportForBounds } from "reactflow";

// fitView centers content in the full pane, but the palette dock
// (`#tools-palette-dock`) is a fixed overlay on the left — and with a panel open
// it occludes a wide strip. Compute the fitted viewport ourselves and bake a
// rightward offset (half the occluded width) into a SINGLE animated setViewport so
// the content lands centered in the visible area.
//
// The previous approach (rf.fitView() then a second rf.setViewport with the
// offset) was broken for animated fits: fitView starts an async transition and
// returns immediately, so reading the viewport back gave the pre-animation value
// and the instant setViewport cancelled the fit — the canvas just shifted right
// instead of focusing the nodes.

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

    const bounds = getRectOfNodes(targetNodes);
    const { x, y, zoom } = getViewportForBounds(
        bounds,
        paneRect.width,
        paneRect.height,
        minZoom,
        maxZoom,
        padding,
    );

    // Half the pane width the dock occludes (measured relative to the pane's left
    // edge), so content centers in the area to the right of the open palette.
    const dock = document.getElementById("tools-palette-dock");
    let xOffset = 0;
    if (dock) {
        const occluded = dock.getBoundingClientRect().right - paneRect.left;
        if (occluded > 0) xOffset = occluded / 2;
    }

    rf.setViewport(
        { x: x + xOffset, y, zoom },
        options?.duration ? { duration: options.duration } : undefined,
    );
    return true;
}
