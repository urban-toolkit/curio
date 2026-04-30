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
    },
    applyInteractions: (map, interactions) => {
        if (typeof map?.setHighlightedIds !== 'function') return;
        for (const i of interactions) {
            const detail = i?.details?.autk;
            if (!detail || detail.kind !== 'highlight-on-map' || !detail.layerId) continue;
            map.setHighlightedIds(detail.layerId, detail.selection ?? []);
        }
        if (typeof map?.draw === 'function') map.draw();
    },
});
