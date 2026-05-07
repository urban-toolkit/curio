# Example: What-if scenarios with Autark

In this example, we walk through a what-if dataflow that lets users pick buildings in Boston, raise their heights with a multiplier widget, and compare the modified scenario against the baseline. The dataflow uses Curio's [Autark integration](12-shadow-analysis.md) to keep the picking-driven workflow entirely in the browser. Building **height** is used as a what-if proxy that's directly visible on the rendered map — replace the compute step with a WebGPU shadow shader (see [Example 12](12-shadow-analysis.md)) when you want a full shadow study.

!!! note "WebGPU required"
    Autark relies on WebGPU. Run this example in a Chromium-based browser (Chrome / Edge) on a machine with a working GPU stack. `navigator.gpu` must be available.

For completeness, we include the template code in each dataflow step.

## Pipeline overview

```
AUTK_DB ─▶ AUTK_COMPUTE ─▶ DATA_POOL ─┬─▶ AUTK_MAP   (baseline + picking)
                                      │
                                      ├─▶ AUTK_MAP   (baseline, side-by-side)
                                      │
                                      └─▶ AUTK_COMPUTE (apply multiplier) ─┬─▶ AUTK_MAP (modified)
                                                                            │
                                                                            └─▶ AUTK_MAP (delta)
```

## Step 1: Loading physical layers (`AUTK_DB`)

Instantiate an `AUTK_DB` node and load the buildings, surface, and parks for Boston via the Overpass API. Autark's spatial database materializes each layer in EPSG:3395 and exposes it as a regular GeoJSON `FeatureCollection`.

```javascript
import { AutkSpatialDb } from '@urban-toolkit/autk-db';

const db = new AutkSpatialDb();
await db.init();

await db.loadOsm({
    queryArea: { geocodeArea: 'Boston' },
    outputTableName: 'table_osm',
    autoLoadLayers: {
        coordinateFormat: 'EPSG:3395',
        layers: ['buildings', 'surface', 'parks'],
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
return layers;
```

## Step 2: Annotate buildings with footprint area and baseline height (`AUTK_COMPUTE`)

The next node walks each building feature, adds a numeric `area` (m²) computed from the polygon ring, and stores the parsed OSM `height` tag in two places: the original value as `baselineHeight`, and a working copy as `height` (mutated by Step 4).

```javascript
const ringArea = (ring) => {
    if (!ring || ring.length < 3) return 0;
    const ox = ring[0][0], oy = ring[0][1];
    let s = 0;
    for (let i = 0; i < ring.length; i++) {
        const j = (i + 1) % ring.length;
        const x1 = ring[i][0] - ox, y1 = ring[i][1] - oy;
        const x2 = ring[j][0] - ox, y2 = ring[j][1] - oy;
        s += x1 * y2 - x2 * y1;
    }
    return Math.abs(s) / 2;
};
const featureArea = (geom) => {
    if (!geom) return null;
    if (geom.type === 'Polygon') return ringArea(geom.coordinates[0]);
    if (geom.type === 'MultiPolygon') return geom.coordinates.reduce((s, p) => s + ringArea(p[0]), 0);
    if (geom.type === 'GeometryCollection') return (geom.geometries || []).reduce((s, g) => s + (featureArea(g) || 0), 0);
    return null;
};
const parseHeight = (h) => {
    if (h == null) return null;
    if (typeof h === 'number') return Number.isFinite(h) ? h : null;
    const m = String(h).match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
};

return arg.map(layer => {
    if (layer.name !== 'table_osm_buildings') return layer;
    const features = layer.geojson.features.map(f => {
        const baseline = parseHeight(f.properties?.height) ?? 10;
        return {
            ...f,
            properties: {
                ...f.properties,
                area: featureArea(f.geometry),
                baselineHeight: baseline,
                height: baseline,
            },
        };
    });
    return { ...layer, geojson: { ...layer.geojson, features } };
});
```

Wire the compute output to a `DATA_POOL` so the same annotated layers can fan out to every downstream view.

## Step 3: Picking-enabled baseline map (`AUTK_MAP`)

Connect the pool to an `AUTK_MAP` node. Calling `updateRenderInfo(layer, { isPick: true, isColorMap: true })` enables click selection on the buildings layer and the picking interaction edge. Buildings clicked on the map gain an `interacted = '1'` flag downstream.

```javascript
const map = new AutkMap(container);
await map.init();

for (const layer of arg) {
    map.loadCollection(layer.name, { collection: layer.geojson, type: layer.type });
}

const buildings = arg.find(l => l.name === 'table_osm_buildings').geojson;
map.updateRenderInfo('table_osm_buildings', { isPick: true, isColorMap: true });
map.updateThematic('table_osm_buildings', { collection: buildings, property: 'properties.height' });
map.draw();
return map;
```

## Step 4: Apply the height multiplier (`AUTK_COMPUTE`)

Add another `AUTK_COMPUTE` node connected to the same data pool. Picked buildings carry `interacted = '1'`, so we multiply only their heights and record the per-building `heightDelta` for the delta view further down.

```javascript
const MULTIPLIER = [!! Height Multiplier$INPUT_VALUE$1.4 !!];

return arg.map(layer => {
    if (layer.name !== 'table_osm_buildings') return layer;
    const features = layer.geojson.features.map(f => {
        const baseline = f.properties?.baselineHeight ?? 10;
        const isInteracted = String(f.properties?.interacted) === '1';
        const newHeight = isInteracted ? baseline * MULTIPLIER : baseline;
        return {
            ...f,
            properties: {
                ...f.properties,
                height: newHeight,
                heightDelta: newHeight - baseline,
            },
        };
    });
    return { ...layer, geojson: { ...layer.geojson, features } };
});
```

The marker `[!! Height Multiplier$INPUT_VALUE$1.4 !!]` exposes a numeric widget on the node so the multiplier can be tuned without re-editing the code.

## Step 5: Modified-scenario view (`AUTK_MAP`)

Render the multiplier output as a second map, coloured by the new `height`. This is the "after" view in the comparison.

```javascript
const map = new AutkMap(container);
await map.init();

for (const layer of arg) {
    map.loadCollection(layer.name, { collection: layer.geojson, type: layer.type });
}

const buildings = arg.find(l => l.name === 'table_osm_buildings').geojson;
map.updateRenderInfo('table_osm_buildings', { isColorMap: true });
map.updateThematic('table_osm_buildings', { collection: buildings, property: 'properties.height' });
map.draw();
return map;
```

## Step 6: Side-by-side baseline view (`AUTK_MAP`)

Add a third `AUTK_MAP` node connected back to the data pool. Setting the thematic property to `properties.baselineHeight` keeps this view fixed on the original heights so it can sit next to the modified map for visual comparison. Picking is left off here.

```javascript
const map = new AutkMap(container);
await map.init();

for (const layer of arg) {
    map.loadCollection(layer.name, { collection: layer.geojson, type: layer.type });
}

const buildings = arg.find(l => l.name === 'table_osm_buildings').geojson;
map.updateRenderInfo('table_osm_buildings', { isColorMap: true });
map.updateThematic('table_osm_buildings', { collection: buildings, property: 'properties.baselineHeight' });
map.draw();
return map;
```

## Step 7: Delta view (`AUTK_MAP`)

The fourth map renders `heightDelta` (modified − baseline). Buildings the user did not pick stay at zero and fade into the background; picked buildings stand out in proportion to how much the multiplier raised them.

```javascript
const map = new AutkMap(container);
await map.init();

for (const layer of arg) {
    map.loadCollection(layer.name, { collection: layer.geojson, type: layer.type });
}

const buildings = arg.find(l => l.name === 'table_osm_buildings').geojson;
map.updateRenderInfo('table_osm_buildings', { isColorMap: true });
map.updateThematic('table_osm_buildings', { collection: buildings, property: 'properties.heightDelta' });
map.draw();
return map;
```

## Final result

The three side-by-side maps now form a what-if comparison: pick buildings on the picker map, edit the multiplier widget, and the modified and delta maps update on the next run. Swapping the multiplier compute node for a [WebGPU shadow shader](12-shadow-analysis.md) extends this same topology into a full shadow-impact study.
