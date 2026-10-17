// The press guard for the Autark node's map canvas: a drag that only passes
// over a map leaves the map's view. Used by the node behavior (autkGrammarBehavior.tsx).
//
// autk-map pans its camera (or, with Shift, turns it) when a pointer moves over
// its canvas with the primary or middle button held, wherever the press began:
// its pointermove handler starts a drag on any such move whose target is the
// canvas. So drawing an edge, dragging a node or drawing a selection box across
// a map moved the map.
//
// While a press that began anywhere but this canvas is held, the canvas ignores
// the pointer (`pointer-events: none`), so no move of that press targets it and
// the element beneath it, its node, gets the move instead. A press on the canvas
// itself is autk-map's own and still pans the map. The canvas takes the pointer
// again when the press ends: on pointerup; on pointercancel (a native drag and
// drop cancels the pointer as it starts, and no pointerup follows its drop); on
// a move with no button held, a release the page never saw; and when the window
// loses focus.
//
// Returns a disposer that removes the window listeners and gives the canvas the
// pointer back. The caller calls it before replacing the canvas and on unmount.
export function attachMapPressGuard(canvas: HTMLCanvasElement): () => void {
    // The canvas's own inline pointer-events while a press elsewhere is held,
    // to put back when it ends; null while no such press is held.
    let before: string | null = null;

    const release = () => {
        if (before === null) return;
        canvas.style.pointerEvents = before;
        before = null;
    };

    const onPointerDown = (e: PointerEvent) => {
        // autk-map pans with the primary and the middle button only.
        if (before !== null || e.target === canvas || (e.button !== 0 && e.button !== 1)) return;
        before = canvas.style.pointerEvents;
        canvas.style.pointerEvents = 'none';
    };

    const onPointerMove = (e: PointerEvent) => {
        if (e.buttons === 0) release();
    };

    const cap: AddEventListenerOptions = { capture: true };
    window.addEventListener('pointerdown', onPointerDown as EventListener, cap);
    window.addEventListener('pointermove', onPointerMove as EventListener, cap);
    window.addEventListener('pointerup', release, cap);
    window.addEventListener('pointercancel', release, cap);
    window.addEventListener('blur', release);

    return () => {
        window.removeEventListener('pointerdown', onPointerDown as EventListener, cap);
        window.removeEventListener('pointermove', onPointerMove as EventListener, cap);
        window.removeEventListener('pointerup', release, cap);
        window.removeEventListener('pointercancel', release, cap);
        window.removeEventListener('blur', release);
        release();
    };
}
