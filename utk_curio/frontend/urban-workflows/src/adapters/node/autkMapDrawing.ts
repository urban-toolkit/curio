/**
 * Autark maps draw on demand, and a map nobody will see again is destroyed.
 *
 * autk-grammar starts each map it makes with autk-map's `draw()`, which draws
 * one frame, then only when the map's picture changes, and every map of the
 * page draws with the same GPU device. autk-map asks for that frame itself
 * after every change it can observe (its camera, its layers, its style, a
 * pick, a window resize). Curio asks a map for a frame with its
 * `requestRender()` after it changes the map itself: `frameMaps` after it
 * moves the camera, and `bleedRasterEdges` after it writes a raster's cells in
 * place, which autk-map cannot observe. A map that nothing changes draws
 * nothing, whether it shows, sits out of view or is hidden in a collapsed
 * scenario.
 *
 * The node keeps the maps its grammar made (`trackMaps`) and destroys them
 * (autk-map's `destroy()`: the GPU textures, the window listeners and the
 * map's controls) when its next run replaces them and when it leaves the
 * page, a deleted node or a closed dataflow (`autkGrammarBehavior`).
 *
 * Every reader of the maps a grammar made takes them from `grammarMaps`.
 *
 * The e2e captures and the map framing check read a map's pixels in the
 * animation frame that renders the map (`renderMapsForReading`): Chrome can
 * read back an idle WebGPU canvas, long after its last frame, as transparent.
 */
import type { AutkMap } from '@urban-toolkit/autk-map';

type KeptMap = Pick<AutkMap, 'requestRender' | 'destroy'>;

/** The maps the nodes keep, until they are destroyed. */
const keptMaps = new Set<KeptMap>();

/**
 * The maps *grammar*'s last run drew, one for each `map` entry of its
 * document, in the document's order (autk-grammar's `maps`).
 */
export function grammarMaps(grammar: unknown): any[] {
    const maps = (grammar as { maps?: unknown } | null | undefined)?.maps;
    return Array.isArray(maps) ? Array.from(maps) : [];
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
 * Destroy the maps a failed run of *grammar* made, which no node keeps:
 * autk-grammar's own `destroy()`, once the node has ended the run's database,
 * its own (autkDbClose `runDatabase`). A grammar that cannot be torn down
 * must not hide the failure that drops it.
 */
export function destroyFailedGrammar(grammar: unknown): void {
    const destroyGrammar = (grammar as { destroy?: () => void } | null | undefined)?.destroy;
    if (typeof destroyGrammar !== 'function') return;
    try {
        destroyGrammar.call(grammar);
    } catch (error) {
        console.warn('[autk-grammar] destroying a failed run failed:', error);
    }
}

/**
 * Stop the camera tour each map of *grammar* plays (autk-grammar's `tours`:
 * the run's, or the one Curio played since), which would go on turning the
 * camera of a map that is gone.
 */
function stopTours(grammar: unknown): void {
    const tours = (grammar as { tours?: unknown } | null | undefined)?.tours;
    if (!Array.isArray(tours)) return;
    for (const tour of tours) {
        try {
            tour?.stop?.();
        } catch (error) {
            console.warn('[autk-map] stopping a camera tour failed:', error);
        }
    }
}

/**
 * Keep each map *grammar* made, for `renderMapsForReading`, until the node
 * drops it. Returns what destroys the maps, their tours stopped first, for
 * the node that drops them.
 */
export function trackMaps(grammar: unknown): () => void {
    const maps: KeptMap[] = grammarMaps(grammar).filter((map) => typeof map?.destroy === 'function');
    for (const map of maps) keptMaps.add(map);
    return () => {
        stopTours(grammar);
        maps.forEach(destroy);
    };
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
