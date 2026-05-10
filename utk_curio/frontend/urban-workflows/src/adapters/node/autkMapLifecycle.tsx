import { createAutkLifecycle } from './autkLifecycleFactory';
import { VisInteractionType } from '../../constants';

const DEFAULT_CODE = `// 'arg' is the layer array — either an Autark layer array
// [{ name: string, type: string, geojson: GeoJSON.FeatureCollection }, ...]
// or a single layer auto-wrapped from an upstream GeoDataFrame / FeatureCollection.
// 'container' is the canvas element rendered inside this node.
// 'AutkMap' is imported from autk-map automatically.
// Return the AutkMap instance to enable bidirectional brushing with linked plots.
const map = new AutkMap(container);
await map.init();
for (const layer of arg) {
    map.loadCollection(layer.name, { collection: layer.geojson, type: layer.type });
}
map.draw();
return map;`;

export const useAutkMapLifecycle = createAutkLifecycle({
    moduleImport: () => import('@urban-toolkit/autk-map'),
    globals: ['AutkMap'],
    container: 'canvas',
    defaultCode: DEFAULT_CODE,
    bidirectional: true,
    autoWrapFeatureCollection: true,
    // Fast path. The lifecycle's default behaviour is to rebuild the
    // entire AutkMap whenever ``data.input`` changes. That is correct
    // when the upstream data was actually recomputed, but it's
    // disastrous when the only change is a selection round-trip from a
    // linked Vega chart (or any other interaction-driven DataPool
    // refresh): every hover frame would tear down and reinitialise
    // WebGPU, leaking GPU memory until the renderer fails with
    // "Not enough memory left".
    //
    // Detect that case by comparing the new layer array to the cached
    // one: same shape, same per-feature property keys (excluding the
    // ``interacted`` flag the DataPool flips), same scalar property
    // values. If everything except ``interacted`` matches, we extract
    // the new selection per layer and tell the factory to apply it
    // through ``setHighlightedIds`` on the live instance instead of
    // rebuilding.
    skipRerunIf: (newArg, oldArg) => {
        if (!Array.isArray(oldArg) || !Array.isArray(newArg)) return false;
        if (oldArg.length !== newArg.length) return false;
        const selectionByLayer: Record<string, number[]> = {};
        for (let li = 0; li < newArg.length; li++) {
            const o = oldArg[li];
            const n = newArg[li];
            if (!o || !n) return false;
            if (o.name !== n.name || o.type !== n.type) return false;
            const og = o.geojson;
            const ng = n.geojson;
            const ofeats = og?.features;
            const nfeats = ng?.features;
            if (!Array.isArray(ofeats) || !Array.isArray(nfeats)) return false;
            if (ofeats.length !== nfeats.length) return false;
            const indices: number[] = [];
            for (let i = 0; i < nfeats.length; i++) {
                const op = ofeats[i].properties || {};
                const np = nfeats[i].properties || {};
                const okeys = Object.keys(op);
                const nkeys = Object.keys(np);
                // ``interacted`` may exist on either side independently;
                // every other key must be present on both with equal
                // scalar values.
                const oset = new Set(okeys.filter((k) => k !== 'interacted'));
                const nset = new Set(nkeys.filter((k) => k !== 'interacted'));
                if (oset.size !== nset.size) return false;
                for (const k of oset) {
                    if (!nset.has(k)) return false;
                    if (op[k] !== np[k]) return false;
                }
                if (String(np.interacted) === '1') indices.push(i);
            }
            selectionByLayer[n.name] = indices;
        }
        return { selectionByLayer };
    },
    // Preserve picking selection across input-driven reruns. Picking
    // emits an interaction → DataPool updates `interacted` → DataPool
    // pushes new output back into this map's input → the lifecycle
    // rebuilds the map. Without rehydration the highlight visibly
    // flashes off; we snapshot every layer's highlightedIds and apply
    // them to the matching layer on the rebuilt map.
    serializeState: (map) => {
        const layers = map?.layerManager?.layers ?? map?._layerManager?.layers;
        if (!layers || typeof layers[Symbol.iterator] !== 'function') return null;
        const state: Record<string, number[]> = {};
        for (const layer of layers) {
            const id = layer?.layerInfo?.id;
            const ids = layer?.highlightedIds;
            if (id && Array.isArray(ids) && ids.length > 0) {
                state[id] = [...ids];
            }
        }
        return Object.keys(state).length > 0 ? state : null;
    },
    restoreState: (map, state) => {
        if (!state || typeof map?.setHighlightedIds !== 'function') return;
        for (const [layerId, ids] of Object.entries(state as Record<string, number[]>)) {
            try {
                map.setHighlightedIds(layerId, ids);
            } catch {
                // Layer may not have been recreated (e.g. removed upstream); skip.
            }
        }
        if (typeof map?.draw === 'function') map.draw();
    },
    bindInteractions: (map, emit, getCurrentInstance) => {
        if (map?.events?.on) {
            map.events.on('picking', ({ selection, layerId }: any) => {
                // Two payloads at once:
                //  - `autk`: kept for AUTK_MAP↔AUTK_PLOT linked brushing
                //    (consumed by autkPlotLifecycle's `applyInteractions`).
                //  - `pick`: Vega-shaped POINT entry that
                //    dataPoolLifecycle.tsx parses out of `details[key].type`,
                //    so picking propagates to a downstream Data Pool's
                //    `interacted` column on Interaction edges.
                emit({
                    autk: { kind: 'pick', selection, layerId },
                    pick: {
                        type: VisInteractionType.POINT,
                        data: Array.isArray(selection) ? selection : [],
                        priority: 1,
                    },
                });
            });
        }

        // Compensate for React Flow's viewport CSS transform.
        // autk-map reads click coords from getBoundingClientRect (visual px,
        // post-transform) and forwards them as if they were canvas-local CSS
        // pixels — at any react-flow zoom != 1 the two disagree, so picks
        // land off-target.
        //
        // Approach: install one capture-phase listener per canvas, lazily
        // (on first call only). The handler resolves the *live* map via the
        // `getCurrentInstance` getter the lifecycle factory provides, so it
        // stays correct after pool propagations rebuild the map. The flag
        // is also stored on the canvas so the listener survives even if
        // bindInteractions runs again on a later full rebuild — we just
        // refresh the getter via a closure-cell on the canvas.
        // We deliberately DO NOT use event.offsetX/Y — Chrome/Edge measure
        // offsetX against the target's *post-transform* box (i.e. visual
        // pixels) under CSS transforms, which would defeat the rescale.
        const canvas: HTMLCanvasElement | undefined = map?.canvas;
        const me = map?._mouseEvents;
        if (canvas && me) {
            if (me._onDblClick) canvas.removeEventListener('dblclick', me._onDblClick, false);
            if (me._onWheel) canvas.removeEventListener('wheel', me._onWheel);

            // Closure cell that always returns the live instance. Replaced
            // on each bindInteractions so listeners installed in earlier
            // rebuilds pick up the latest getter without being re-attached.
            (canvas as any).__autkCurrentGetter = getCurrentInstance;

            const resolveCurrent = (): any => {
                const getter = (canvas as any).__autkCurrentGetter;
                return typeof getter === 'function' ? getter() : null;
            };

            const localCoords = (e: MouseEvent | WheelEvent): [number, number] => {
                const cur = resolveCurrent();
                const cw = cur?.renderer?.cssWidth || canvas.offsetWidth;
                const ch = cur?.renderer?.cssHeight || canvas.offsetHeight;
                const rect = canvas.getBoundingClientRect();
                const sx = rect.width > 0 ? cw / rect.width : 1;
                const sy = rect.height > 0 ? ch / rect.height : 1;
                return [(e.clientX - rect.left) * sx, (e.clientY - rect.top) * sy];
            };

            // Install capture-phase listeners exactly once per canvas, so
            // they fire before autk-map's stock dblclick/wheel even if its
            // listeners survive our removal attempts.
            if (!('__autkPersistentDblHandler' in canvas)) {
                const persistentDbl = (e: MouseEvent) => {
                    const cur = resolveCurrent();
                    const layer = cur?.activePickingLayer;
                    if (!layer?.layerRenderInfo?.isPick) return;
                    const [x, y] = localCoords(e);
                    if (typeof window !== 'undefined' && (window as any).__curioAutkDebug) {
                        const rect = canvas.getBoundingClientRect();
                        // eslint-disable-next-line no-console
                        console.debug('[autk pick]', {
                            client: [e.clientX, e.clientY],
                            rectLeftTop: [rect.left, rect.top],
                            rectWH: [rect.width, rect.height],
                            cssWH: [cur?.renderer?.cssWidth, cur?.renderer?.cssHeight],
                            offsetWH: [canvas.offsetWidth, canvas.offsetHeight],
                            computed: [x, y],
                            layerId: layer?.layerInfo?.id,
                            dpr: window.devicePixelRatio,
                        });
                    }
                    layer.layerRenderInfo.pickedComps = [x, y];
                    e.preventDefault();
                    e.stopImmediatePropagation();
                };
                canvas.addEventListener('dblclick', persistentDbl, true);
                (canvas as any).__autkPersistentDblHandler = persistentDbl;

                const persistentWheel = (e: WheelEvent) => {
                    const cur = resolveCurrent();
                    if (!cur?.camera || !cur?.renderer) return;
                    const cw = cur.renderer.cssWidth;
                    const ch = cur.renderer.cssHeight;
                    if (cw <= 0 || ch <= 0) return;
                    const [x, y] = localCoords(e);
                    cur.camera.zoom(e.deltaY * 0.01, x / cw, 1 - y / ch);
                    e.preventDefault();
                    e.stopImmediatePropagation();
                };
                canvas.addEventListener('wheel', persistentWheel, { passive: false, capture: true });
                (canvas as any).__autkPersistentWheelHandler = persistentWheel;
            }
        }
    },
    applyInteractions: (map, interactions) => {
        if (typeof map?.setHighlightedIds !== 'function') return;
        for (const i of interactions) {
            const detail = i?.details?.autk;
            if (!detail) continue;
            // Plot brush/click → highlight matching features on the map's
            // active picking layer. The plot's selection is an array of
            // source feature ids, which line up 1:1 with the picking layer's
            // component ids for non-buildings layers.
            if (typeof detail.kind === 'string' && detail.kind.startsWith('chart-')) {
                const layerId = map.activePickingLayer?.layerInfo?.id;
                if (layerId) map.setHighlightedIds(layerId, detail.selection ?? []);
                continue;
            }
            // Explicit cross-node highlight: caller specifies the target layer.
            if (detail.kind === 'highlight-on-map' && detail.layerId) {
                map.setHighlightedIds(detail.layerId, detail.selection ?? []);
            }
        }
        if (typeof map?.draw === 'function') map.draw();
    },
});
