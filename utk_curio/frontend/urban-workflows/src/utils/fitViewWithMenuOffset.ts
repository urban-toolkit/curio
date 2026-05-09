import type { ReactFlowInstance, FitViewOptions } from "reactflow";

// fitView centers content in the full canvas, but the ToolsMenu (id="tools-menu")
// is a fixed-position overlay on the left edge. After fitView, shift the viewport
// right by half the menu's right-edge so content is centered in the visible area.
// menu.right / 2 == ((menuRight + viewportWidth) / 2) - (viewportWidth / 2),
// i.e. (visible-region center) - (full-canvas center).
export function fitViewWithMenuOffset(
    rf: ReactFlowInstance,
    options?: FitViewOptions,
): boolean {
    const fitApplied = rf.fitView(options);
    if (!fitApplied) return false;

    const menuEl = document.getElementById("tools-menu");
    if (menuEl) {
        const xOffset = menuEl.getBoundingClientRect().right / 2;
        if (xOffset > 0) {
            const vp = rf.getViewport();
            rf.setViewport({ ...vp, x: vp.x + xOffset });
        }
    }
    return true;
}
