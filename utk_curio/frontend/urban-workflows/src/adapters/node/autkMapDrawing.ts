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
 */
import type { AutkMap } from '@urban-toolkit/autk-map';

type DrawnMap = Pick<AutkMap, 'draw' | 'requestRender' | 'destroy'>;

/** The maps autk-grammar made: its registry keeps one for each layer a map draws. */
function mapsOf(grammar: any): DrawnMap[] {
    const registry = grammar?._mapRegistry;
    if (!(registry instanceof Map)) return [];
    return [...new Set<DrawnMap>(registry.values())].filter((map) => typeof map?.draw === 'function');
}

/** Destroy *map*: its GPU textures, window listeners and controls. */
function destroy(map: DrawnMap): void {
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
    for (const map of maps) map.draw({ onDemand: true });
    return () => maps.forEach(destroy);
}
