import React from 'react';
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

// AUTK_DB executes server-side via the Node.js sandbox (CodeEditor.tsx
// routes ``isJsNode`` through ``data.jsInterpreter``), so this lifecycle
// does NOT import @urban-toolkit/autk-db in the browser — that package
// pulls in node:path / node:module / node:worker_threads and would break
// webpack. We only render a placeholder output panel so NodeEditor exposes
// the standard "output" tab; execution status (Done / Error) is set by
// CodeEditor's processExecutionResult callback after the sandbox replies.
const AUTK_DB_OUTPUT_PLACEHOLDER = (
    <div
        className="nowheel nodrag"
        style={{
            padding: 12,
            color: '#666',
            fontSize: '0.85em',
            lineHeight: 1.4,
        }}
    >
        AutkDB executes server-side via the Node.js sandbox.
        The returned layer array is forwarded to downstream nodes.
    </div>
);

export const useAutkDbLifecycle: NodeLifecycleHook = (data, _nodeState) => {
    const hasExistingCode = !!(data.defaultCode || (data as any).code);
    return {
        contentComponent: AUTK_DB_OUTPUT_PLACEHOLDER,
        defaultValueOverride: hasExistingCode ? undefined : DEFAULT_CODE,
    };
};
