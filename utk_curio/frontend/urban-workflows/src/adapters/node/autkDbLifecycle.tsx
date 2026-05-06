import { NodeLifecycleHook } from '../../registry/types';

const DEFAULT_CODE = `import { AutkSpatialDb } from '@urban-toolkit/autk-db';

const db = new AutkSpatialDb();
await db.init();

await db.loadOsm({
    queryArea: { geocodeArea: 'Chicago', areas: ['Loop'] },
    outputTableName: 'table_osm',
    autoLoadLayers: {
        coordinateFormat: 'EPSG:3395',
        layers: ['surface', 'parks', 'water'],
        dropOsmTable: true,
    },
});

const layers = [];
for (const layer of db.getLayerTables()) {
    layers.push({
        name: layer.name,
        type: layer.type,
        geojson: await db.getLayer(layer.name),
    });
}
return layers;`;

export const useAutkDbLifecycle: NodeLifecycleHook = (data, _nodeState) => {
    // Only seed the boilerplate when the node has no code yet (fresh palette drop).
    // When loading an example, data.defaultCode carries the example's content and
    // must take precedence.
    if (data.defaultCode || data.code) return {};
    return { defaultValueOverride: DEFAULT_CODE };
};
