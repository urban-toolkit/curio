// The map interaction zoom fix for the Autark node: autk-map's pointer math,
// corrected for the React Flow viewport scale. Used by the node behavior (autkGrammarBehavior.tsx).

// Flag stamped on the synthetic events we re-dispatch, so the interceptor
// recognizes its own event and lets it through to autk-map untouched.
const ZOOM_FIX_CORRECTED = '__curioMapZoomCorrected';

// PointerEvent isn't constructable in every test DOM; fall back to MouseEvent
// (autk-map reads only MouseEvent-level fields — clientX/Y, buttons, target — off
// the pointer events it handles).
const PointerEventCtor: typeof MouseEvent =
    typeof PointerEvent !== 'undefined' ? (PointerEvent as unknown as typeof MouseEvent) : MouseEvent;

// Correct autk-map's pointer math for the React Flow viewport scale.
//
// Each node renders inside React Flow's viewport, which is CSS-scaled by the
// current zoom (`transform: scale(zoom)`). autk-map reads pointer positions from
// getBoundingClientRect() — which is *post*-scale — but feeds them to camera /
// picking math sized from the canvas's *unscaled* offsetWidth/offsetHeight (its
// renderer resizes from offsetWidth). At any zoom != 1 the two disagree by the
// zoom factor, so:
//   • picking (double-click) lands toward the canvas's top-left corner,
//   • wheel-zoom recenters on the wrong point,
//   • drag-pan moves the map too slowly — all by the zoom factor.
//
// Curio owns this canvas element, so intercept the relevant events in the capture
// phase on `window` (above autk-map's document/canvas listeners), suppress the
// mis-scaled native event, and re-dispatch an equivalent one *on the canvas* whose
// client coordinates are mapped back into the canvas's unscaled CSS space — exactly
// what autk-map's math assumes (the conversion is the same for all three: each
// divides a screen-space delta by the unscaled cssWidth, so each needs the delta
// un-scaled first). `scale` is read straight off the DOM (rect.width / offsetWidth),
// so this tracks any ancestor transform without needing React Flow's zoom value.
// (The real fix belongs upstream in autk-map's coordinate conversion; this is the
// in-Curio compensation until then.)
//
// Returns a disposer that removes the window listeners — they outlive the canvas,
// so the caller must call it before replacing the canvas and on unmount.
export function attachMapInteractionZoomFix(canvas: HTMLCanvasElement): () => void {
    // Mirrors autk-map's drag state so pointermove/up that wander off the canvas
    // mid-drag stay corrected (autk-map keeps dragging via its document listeners
    // regardless of the event target).
    let dragging = false;

    // The CSS scale ancestors apply to the canvas (React Flow zoom), or null when
    // there's nothing to correct (no layout yet, or scale ~ 1).
    const measure = (): { rect: DOMRect; sx: number; sy: number } | null => {
        const rect = canvas.getBoundingClientRect();
        const lw = canvas.offsetWidth, lh = canvas.offsetHeight;
        if (lw <= 0 || lh <= 0) return null;
        const sx = rect.width / lw, sy = rect.height / lh;
        if (Math.abs(sx - 1) < 0.001 && Math.abs(sy - 1) < 0.001) return null;
        return { rect, sx, sy };
    };

    // Map a client coordinate from rendered (scaled) space back to the unscaled CSS
    // space autk-map expects.
    const cx = (rect: DOMRect, sx: number, clientX: number) => rect.left + (clientX - rect.left) / sx;
    const cy = (rect: DOMRect, sy: number, clientY: number) => rect.top + (clientY - rect.top) / sy;

    const mine = (e: Event) => (e as any)[ZOOM_FIX_CORRECTED] === true;

    const onDblClick = (e: MouseEvent) => {
        if (mine(e) || e.target !== canvas) return;
        const m = measure();
        if (!m) return;
        e.stopImmediatePropagation();
        e.preventDefault();
        const corrected = new MouseEvent('dblclick', {
            bubbles: true, cancelable: true, view: window,
            button: e.button, buttons: e.buttons,
            clientX: cx(m.rect, m.sx, e.clientX),
            clientY: cy(m.rect, m.sy, e.clientY),
        });
        (corrected as any)[ZOOM_FIX_CORRECTED] = true;
        canvas.dispatchEvent(corrected);
    };

    const onWheel = (e: WheelEvent) => {
        if (mine(e) || e.target !== canvas) return;
        const m = measure();
        if (!m) return;
        e.stopImmediatePropagation();
        e.preventDefault();
        const corrected = new WheelEvent('wheel', {
            bubbles: true, cancelable: true, view: window,
            deltaX: e.deltaX, deltaY: e.deltaY, deltaZ: e.deltaZ, deltaMode: e.deltaMode,
            ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey, metaKey: e.metaKey,
            button: e.button, buttons: e.buttons,
            clientX: cx(m.rect, m.sx, e.clientX),
            clientY: cy(m.rect, m.sy, e.clientY),
        });
        (corrected as any)[ZOOM_FIX_CORRECTED] = true;
        canvas.dispatchEvent(corrected);
    };

    const redispatchPointer = (e: PointerEvent, m: { rect: DOMRect; sx: number; sy: number }) => {
        e.stopImmediatePropagation();
        e.preventDefault();
        const init: any = {
            bubbles: true, cancelable: true, view: window,
            button: e.button, buttons: e.buttons,
            ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey, metaKey: e.metaKey,
            clientX: cx(m.rect, m.sx, e.clientX),
            clientY: cy(m.rect, m.sy, e.clientY),
            // Pointer-specific fields (ignored by the MouseEvent fallback).
            pointerId: e.pointerId, pointerType: e.pointerType, isPrimary: e.isPrimary,
        };
        const corrected = new PointerEventCtor(e.type, init);
        (corrected as any)[ZOOM_FIX_CORRECTED] = true;
        canvas.dispatchEvent(corrected);
    };

    const onPointerDown = (e: PointerEvent) => {
        if (mine(e)) return;
        if (e.target === canvas && (e.button === 0 || e.button === 1)) dragging = true;
        if (!dragging) return;
        const m = measure();
        if (!m) return; // scale ~ 1: leave the native event alone (drag still tracked)
        redispatchPointer(e, m);
    };

    const onPointerMove = (e: PointerEvent) => {
        if (mine(e)) return;
        // Mirror autk-map's alternate drag-start (button already held on entry).
        if (!dragging && e.target === canvas && (e.buttons === 1 || e.buttons === 4)) dragging = true;
        if (!dragging) return;
        const m = measure();
        if (!m) return;
        redispatchPointer(e, m);
    };

    const onPointerUp = (e: PointerEvent) => {
        if (mine(e)) return;
        // autk-map's pointerup/cancel use no coordinates; just clear our mirrored
        // state and let the native event through so autk-map ends the drag.
        dragging = false;
    };

    const cap: AddEventListenerOptions = { capture: true };
    const wheelCap: AddEventListenerOptions = { capture: true, passive: false };
    window.addEventListener('dblclick', onDblClick as EventListener, cap);
    window.addEventListener('wheel', onWheel as EventListener, wheelCap);
    window.addEventListener('pointerdown', onPointerDown as EventListener, cap);
    window.addEventListener('pointermove', onPointerMove as EventListener, cap);
    window.addEventListener('pointerup', onPointerUp as EventListener, cap);
    window.addEventListener('pointercancel', onPointerUp as EventListener, cap);

    return () => {
        window.removeEventListener('dblclick', onDblClick as EventListener, cap);
        window.removeEventListener('wheel', onWheel as EventListener, wheelCap);
        window.removeEventListener('pointerdown', onPointerDown as EventListener, cap);
        window.removeEventListener('pointermove', onPointerMove as EventListener, cap);
        window.removeEventListener('pointerup', onPointerUp as EventListener, cap);
        window.removeEventListener('pointercancel', onPointerUp as EventListener, cap);
    };
}
