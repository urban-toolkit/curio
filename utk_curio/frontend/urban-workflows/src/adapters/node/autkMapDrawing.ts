/**
 * Autark maps draw on demand, and a map nobody will see again is destroyed.
 *
 * autk-grammar starts each map it makes drawing on every animation frame
 * (`AutkMap.draw()`), whether or not anything changed, and every map of the
 * page draws with the same GPU device. Curio switches each map to autk-map's
 * on-demand rendering as soon as the grammar has made it
 * (`draw({ onDemand: true })`): the map draws one frame, then only when its
 * picture changes. autk-map asks for that frame itself after every change it
 * can observe (its camera, its layers, its style, a pick, a window resize);
 * where Curio changes a map in a way it cannot observe, Curio calls the map's
 * `requestRender()` (`frameMaps`, `recolorRasters`). A map that nothing
 * changes draws nothing, whether it shows, sits out of view or is hidden in a
 * collapsed scenario.
 *
 * The node destroys its maps (autk-map's `destroy()`: the GPU textures, the
 * window listeners and the map's controls) when its next run replaces them and
 * when it leaves the page, a deleted node or a closed dataflow
 * (`autkGrammarBehavior`).
 *
 * The e2e captures and the map framing check read a map's pixels in the
 * animation frame that renders the map (`renderMapsForReading`): Chrome can
 * read back an idle WebGPU canvas, long after its last frame, as transparent.
 */
import type { AutkMap } from '@urban-toolkit/autk-map';

type DrawnMap = Pick<AutkMap, 'draw' | 'requestRender' | 'destroy'>;

/** The maps drawing on demand, until they are destroyed. */
const onDemandMaps = new Set<DrawnMap>();

/** The maps autk-grammar made: its registry keeps one for each layer a map draws. */
function mapsOf(grammar: any): DrawnMap[] {
    const registry = grammar?._mapRegistry;
    if (!(registry instanceof Map)) return [];
    return [...new Set<DrawnMap>(registry.values())].filter((map) => typeof map?.draw === 'function');
}

/** Destroy *map*: its GPU textures, window listeners and controls. */
function destroy(map: DrawnMap): void {
    onDemandMaps.delete(map);
    try {
        map.destroy();
    } catch (error) {
        // A map that cannot be torn down must not fail the run that replaces it.
        console.warn('[autk-map] destroying a map failed:', error);
    }
}

/**
 * Switch each map *grammar* made to on-demand rendering: it draws one frame
 * now, then only when its picture changes. Returns what destroys the maps,
 * for the node that drops them.
 */
export function drawMapsOnDemand(grammar: unknown): () => void {
    const maps = mapsOf(grammar);
    for (const map of maps) {
        map.draw({ onDemand: true });
        onDemandMaps.add(map);
    }
    return () => maps.forEach(destroy);
}

/**
 * Ask every on-demand map for a frame, and resolve inside the animation frame
 * that renders them. Code that goes on from the returned promise, before it
 * awaits anything else, reads each map canvas with the picture just rendered
 * into it. A page that is hidden runs no frames, so there it resolves at once.
 */
export function renderMapsForReading(): Promise<void> {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return Promise.resolve();
    for (const map of onDemandMaps) map.requestRender();
    // Asked after the maps' own frames, so it runs after them in the same frame.
    return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

// The e2e captures and the map framing check read map canvases through it
// (test_frontend/utils/images.py, node_drawings.py).
if (typeof window !== 'undefined') (window as any).__curio_renderMapsForReading = renderMapsForReading;
