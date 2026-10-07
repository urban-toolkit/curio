/**
 * Each Autark map draws only while its canvas has a layout box, and a map
 * nobody will see again is destroyed.
 *
 * autk-map draws a map on every animation frame from the moment autk-grammar
 * starts it (`AutkMap.draw`) until the map is destroyed, whether or not anyone
 * can see it, and every map of the page draws with the same GPU device. So a
 * map draws while its canvas has a layout box: a canvas with `display: none`
 * somewhere above it (a collapsed scenario's member, a minimized node, a
 * node's other tab, a dashboard's unpinned node) or no longer in the page
 * stops its map's frame loop, and given its box back, the map draws again at
 * once. One ResizeObserver watches the canvas of every map Curio draws:
 * hiding or showing a canvas changes its size between none and its own. A map
 * scrolled or panned out of view keeps drawing.
 *
 * autk-map has no call that stops its loop. It keeps the frame it asked for in
 * `_animationFrameId`; cancelling that frame stops the loop, and its own
 * `draw()` starts it again. `autkMapDrawing.test.ts` holds autk-map to that.
 *
 * The node destroys its maps (autk-map's `destroy()`: the frame loop, the GPU
 * textures, the window listeners and the map's controls) when its next run
 * replaces them and when it leaves the page, a deleted node or a closed
 * dataflow (`autkGrammarBehavior`).
 */

/** What Curio reads of an autk-map map. */
type DrawnMap = {
    canvas?: Element | null;
    draw?: (fps?: number) => void;
    destroy?: () => void;
    _animationFrameId?: number | null;
    _isDestroyed?: boolean;
};

/** The map each watched canvas draws. */
const mapOfCanvas = new WeakMap<Element, DrawnMap>();
let observer: ResizeObserver | null = null;

/** Whether *canvas* has a layout box: in the page, with no `display: none` above it. */
function laidOut(canvas: Element): boolean {
    return canvas.isConnected && canvas.getClientRects().length > 0;
}

/** Stop *map*'s frame loop. What it last drew stays on its canvas. */
function pause(map: DrawnMap): void {
    if (map._animationFrameId == null) return;
    cancelAnimationFrame(map._animationFrameId);
    map._animationFrameId = null;
}

/** Start *map*'s frame loop again, unless it runs or is destroyed. */
function resume(map: DrawnMap): void {
    if (map._isDestroyed || map._animationFrameId != null) return;
    map.draw?.();
}

/** Destroy *map*: its frame loop, GPU textures, window listeners and controls. */
function destroy(map: DrawnMap): void {
    try {
        map.destroy?.();
    } catch (error) {
        // A map that cannot be torn down must not fail the run that replaces it.
        console.warn('[autk-map] destroying a map failed:', error);
        pause(map);
    }
}

/** Let *map* draw while *canvas* has a layout box, and stop it while not. */
function follow(canvas: Element, map: DrawnMap): void {
    if (laidOut(canvas)) resume(map);
    else pause(map);
}

function onReports(entries: ResizeObserverEntry[]): void {
    for (const { target } of entries) {
        const map = mapOfCanvas.get(target);
        if (!map) continue;
        follow(target, map);
        // Curio never puts a canvas back once it has left the page.
        if (!target.isConnected) unwatch(target);
    }
}

function unwatch(canvas: Element): void {
    mapOfCanvas.delete(canvas);
    observer?.unobserve(canvas);
}

/** The maps autk-grammar drew: its registry keeps one for each layer a map draws. */
function mapsOf(grammar: any): DrawnMap[] {
    const registry = grammar?._mapRegistry;
    if (!(registry instanceof Map)) return [];
    return [...new Set<DrawnMap>(registry.values())].filter(
        (map) => map?.canvas instanceof Element && typeof map.draw === 'function',
    );
}

/**
 * Let each map of *grammar* draw only while its canvas has a layout box: judged
 * now, and again each time the observer reports the canvas's size changed.
 * Returns what destroys the maps, for the node that drops them.
 */
export function drawMapsWhileShown(grammar: unknown): () => void {
    const maps = mapsOf(grammar);
    if (maps.length === 0) return () => {};
    const destroyAll = () => maps.forEach(destroy);
    if (typeof ResizeObserver === 'undefined') return destroyAll;
    observer ??= new ResizeObserver(onReports);
    for (const map of maps) {
        const canvas = map.canvas as Element;
        const previous = mapOfCanvas.get(canvas);
        // Stopped, not destroyed: the canvas's WebGPU context is the new map's
        // too, and destroying the old map would unconfigure it.
        if (previous && previous !== map) pause(previous);
        mapOfCanvas.set(canvas, map);
        observer.observe(canvas);
        // The observer reports nothing for a canvas that starts with no box.
        follow(canvas, map);
    }
    return () => {
        for (const map of maps) {
            const canvas = map.canvas as Element;
            if (mapOfCanvas.get(canvas) === map) unwatch(canvas);
        }
        destroyAll();
    };
}
