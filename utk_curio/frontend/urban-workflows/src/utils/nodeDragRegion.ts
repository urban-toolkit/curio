/**
 * Whether a press on `target` would drag the node `nodeEl`: React Flow's own
 * rule (its useDrag filter), nothing from the target up to the node marked
 * `nodrag`. Editors, outputs, charts, maps and the connection dots carry it, so
 * they keep their own gestures there.
 */
export function isNodeDragRegion(target: EventTarget | null, nodeEl: Element | null): boolean {
    if (!(target instanceof Element) || !nodeEl || !nodeEl.contains(target)) return false;
    for (let el: Element | null = target; el; el = el.parentElement) {
        if (el.classList.contains("nodrag")) return false;
        if (el === nodeEl) return true;
    }
    return false;
}
