import type { Node } from "reactflow";

/**
 * Whether a press on `target` would drag the node `nodeEl`: React Flow's own
 * rule (its useDrag filter), nothing from the target up to the node marked
 * `nodrag`. Editors, outputs, charts, maps and the connection dots carry it, so
 * they keep their own gestures there. The rule reads `nodrag` only, so it finds
 * the same region on a node that cannot drag, as on a read-only canvas.
 */
export function isNodeDragRegion(target: EventTarget | null, nodeEl: Element | null): boolean {
    if (!(target instanceof Element) || !nodeEl || !nodeEl.contains(target)) return false;
    for (let el: Element | null = target; el; el = el.parentElement) {
        if (el.classList.contains("nodrag")) return false;
        if (el === nodeEl) return true;
    }
    return false;
}

/** React Flow's class for what its pane leaves alone: a press there does not
 *  pan the view, and a double-click does not zoom it. */
const NO_PAN_CLASS = "nopan";

/**
 * `nodes`, each with React Flow's `nopan` class. React Flow gives that class
 * only to a node that drags, so on a canvas whose nodes do not drag (a
 * read-only one) its pane pans on a press on a node and zooms 2x at the pointer
 * on a double-click, and the double-click never reaches `onNodeDoubleClick`.
 * Marked, those nodes are left to their own gestures as draggable ones are, and
 * a double-click where a node would drag zooms onto it, as on an editable canvas.
 */
export function keepPaneOffNodes<N extends Node>(nodes: N[]): N[] {
    return nodes.map((node) => {
        const classes = (node.className ?? "").split(/\s+/).filter(Boolean);
        if (classes.includes(NO_PAN_CLASS)) return node;
        return { ...node, className: [...classes, NO_PAN_CLASS].join(" ") };
    });
}
