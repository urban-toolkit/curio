import type { ReactFlowInstance, FitViewOptions } from "reactflow";

// fitView centers content in the full canvas, but the palette dock (`#tools-palette-dock`)
// is a fixed overlay on the left (built-in tools + packages control). Shift the viewport
// right by half the dock's width so content is centered in the visible area.

export function fitViewWithMenuOffset(
    rf: ReactFlowInstance,
    options?: FitViewOptions,
): boolean {
    const fitApplied = rf.fitView(options);
    if (!fitApplied) return false;

    const dock = document.getElementById("tools-palette-dock");
    if (dock) {
        const xOffset = dock.getBoundingClientRect().right / 2;
        if (xOffset > 0) {
            const vp = rf.getViewport();
            rf.setViewport({ ...vp, x: vp.x + xOffset });
        }
    }
    return true;
}
