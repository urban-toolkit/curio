import { createAutkLifecycle } from './autkLifecycleFactory';

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
    moduleImport: () => import('autk-map'),
    globals: ['AutkMap'],
    container: 'canvas',
    defaultCode: DEFAULT_CODE,
    bidirectional: true,
    autoWrapFeatureCollection: true,
    bindInteractions: (map, emit) => {
        if (map?.events?.on) {
            map.events.on('picking', ({ selection, layerId }: any) => {
                emit({ autk: { kind: 'pick', selection, layerId } });
            });
        }

        // Compensate for React Flow's viewport CSS transform.
        // autk-map reads click coords from getBoundingClientRect (visual px,
        // post-transform) but normalizes against canvas.offsetWidth (layout
        // px). At any react-flow zoom != 1 the two disagree, so picks land
        // off-target.
        //
        // Approach: remove autk-map's own dblclick / wheel listeners and
        // replace them with versions that scale visual click coords up to
        // layout coords before handing off to the same map APIs.
        const canvas: HTMLCanvasElement | undefined = map?.canvas;
        const me = map?._mouseEvents;
        if (canvas && me) {
            // Remove autk-map's stock handlers so they don't pick at wrong coords.
            if (me._onDblClick) canvas.removeEventListener('dblclick', me._onDblClick, false);
            if (me._onWheel) canvas.removeEventListener('wheel', me._onWheel);

            const prevDbl = (canvas as any).__autkScaledDbl;
            if (prevDbl) canvas.removeEventListener('dblclick', prevDbl, false);
            const dblHandler = (e: MouseEvent) => {
                e.preventDefault();
                e.stopPropagation();
                const rect = canvas.getBoundingClientRect();
                const sx = rect.width > 0 ? canvas.offsetWidth / rect.width : 1;
                const sy = rect.height > 0 ? canvas.offsetHeight / rect.height : 1;
                const x = (e.clientX - rect.left) * sx;
                const y = (e.clientY - rect.top) * sy;
                const layer = map.activePickingLayer;
                if (!layer?.layerRenderInfo?.isPick) return;
                layer.layerRenderInfo.pickedComps = [x, y];
            };
            canvas.addEventListener('dblclick', dblHandler, false);
            (canvas as any).__autkScaledDbl = dblHandler;

            const prevWheel = (canvas as any).__autkScaledWheel;
            if (prevWheel) canvas.removeEventListener('wheel', prevWheel);
            const wheelHandler = (e: WheelEvent) => {
                if (!map?.camera || !map?.renderer) return;
                e.preventDefault();
                e.stopPropagation();
                const rect = canvas.getBoundingClientRect();
                const sx = rect.width > 0 ? canvas.offsetWidth / rect.width : 1;
                const sy = rect.height > 0 ? canvas.offsetHeight / rect.height : 1;
                const x = (e.clientX - rect.left) * sx;
                const y = (e.clientY - rect.top) * sy;
                const cw = map.renderer.cssWidth;
                const ch = map.renderer.cssHeight;
                if (cw <= 0 || ch <= 0) return;
                map.camera.zoom(e.deltaY * 0.01, x / cw, 1 - y / ch);
            };
            canvas.addEventListener('wheel', wheelHandler, { passive: false });
            (canvas as any).__autkScaledWheel = wheelHandler;
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
