/**
 * Autark maps draw on demand, and a map nobody will see again is destroyed.
 *
 * autk-grammar starts each map it makes with autk-map's `draw()`, which draws
 * one frame, then only when the map's picture changes, and every map of the
 * page draws with the same GPU device. autk-map asks for that frame itself
 * after every change it can observe (its camera, its layers, its style, a
 * pick, a window resize). Curio asks a map for a frame with its
 * `requestRender()` after it changes the map itself: `frameMaps` after it
 * moves the camera, and `recolorRasters` after it writes a raster's cells in
 * place, which autk-map cannot observe. A map that nothing changes draws
 * nothing, whether it shows, sits out of view or is hidden in a collapsed
 * scenario.
 *
 * The node keeps the maps its grammar made (`trackMaps`) and destroys them
 * (autk-map's `destroy()`: the GPU textures, the window listeners and the
 * map's controls) when its next run replaces them and when it leaves the
 * page, a deleted node or a closed dataflow (`autkGrammarBehavior`).
 *
 * The e2e captures and the map framing check read a map's pixels in the
 * animation frame that renders the map (`renderMapsForReading`): Chrome can
 * read back an idle WebGPU canvas, long after its last frame, as transparent.
 */
import type { AutkMap } from '@urban-toolkit/autk-map';

type KeptMap = Pick<AutkMap, 'requestRender' | 'destroy'>;

/** The maps the nodes keep, until they are destroyed. */
const keptMaps = new Set<KeptMap>();

/** The maps autk-grammar made: its registry keeps one for each layer a map draws. */
function mapsOf(grammar: any): KeptMap[] {
    const registry = grammar?._mapRegistry;
    if (!(registry instanceof Map)) return [];
    return [...new Set<KeptMap>(registry.values())].filter((map) => typeof map?.destroy === 'function');
}

/** Destroy *map*: its GPU textures, window listeners and controls. */
function destroy(map: KeptMap): void {
    keptMaps.delete(map);
    try {
        map.destroy();
    } catch (error) {
        // A map that cannot be torn down must not fail the run that replaces it.
        console.warn('[autk-map] destroying a map failed:', error);
    }
}

/**
 * Keep each map *grammar* made, for `renderMapsForReading`, until the node
 * drops it. Returns what destroys the maps, for the node that drops them.
 */
export function trackMaps(grammar: unknown): () => void {
    const maps = mapsOf(grammar);
    for (const map of maps) keptMaps.add(map);
    return () => maps.forEach(destroy);
}

/**
 * Ask every map the nodes keep for a frame, and resolve inside the animation
 * frame that renders them. Code that goes on from the returned promise, before
 * it awaits anything else, reads each map canvas with the picture just
 * rendered into it. A page that is hidden runs no frames, so there it resolves
 * at once.
 */
export function renderMapsForReading(): Promise<void> {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return Promise.resolve();
    for (const map of keptMaps) map.requestRender();
    // Asked after the maps' own frames, so it runs after them in the same frame.
    return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

// The e2e captures and the map framing check read map canvases through it
// (test_frontend/utils/images.py, node_drawings.py).
if (typeof window !== 'undefined') (window as any).__curio_renderMapsForReading = renderMapsForReading;
