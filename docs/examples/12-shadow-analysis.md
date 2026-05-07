# Example: Shadow analysis with Autark

In this example we use Curio's Autark integration to estimate how many minutes of shadow a single Chicago Loop building casts onto each surrounding road segment over the course of a June day. The dataflow has five nodes — load OSM, run a WebGPU shader, filter to the shadowed subset, render a thematic map, and plot a brushable histogram.

It is a stripped-down translation of the upstream Autark use case at [github.com/urban-toolkit/autark/tree/main/usecases/src/shadows](https://github.com/urban-toolkit/autark/tree/main/usecases/src/shadows). The upstream version supports per-month variants, ground-truth baselines, and live picking; this example deliberately omits all of those to keep the focus on the GPU compute step.

!!! note "WebGPU required"
    Autark relies on WebGPU. Run this example in a Chromium-based browser (Chrome / Edge) on a machine with a working GPU stack.

## Pipeline overview

```text
shadow-db ─▶ shadow-shader ─┬─▶ shadow-map ◀──────────────┐
                            │                              │ Interaction
                            └─▶ shadow-shaded-roads ─▶ shadow-histogram
```

The graph forks at `shadow-shader`: the **map** wants the full road network for context (so unshadowed roads remain visible), while the **histogram** wants only the segments that were actually shadowed (otherwise the zero-bin dominates the chart). The Interaction edge between map and histogram keeps brushing in sync.

## Step 1: Load OSM (`AUTK_DB`)

The DB node fetches Chicago Loop layers via the Overpass API and returns them as Autark layer objects.

```javascript
import { AutkSpatialDb } from '@urban-toolkit/autk-db';

const db = new AutkSpatialDb();
await db.init();

await db.loadOsm({
    queryArea: { geocodeArea: 'Chicago', areas: ['Loop'] },
    outputTableName: 'table_osm',
    autoLoadLayers: {
        coordinateFormat: 'EPSG:3395',
        layers: ['surface', 'parks', 'water', 'roads', 'buildings'],
        dropOsmTable: true,
    },
});

const layers = [];
for (const layer of db.getLayerTables()) {
    layers.push({ name: layer.name, type: layer.type, geojson: await db.getLayer(layer.name) });
}
return layers;
```

## Step 2: GPU shadow shader (`AUTK_COMPUTE`)

The shader node grabs the first OSM building, extracts its outer ring, and runs a WGSL shader that walks daylight hours 07:00–19:00 on the June solstice. For each hour it computes the sun azimuth and altitude, projects the building footprint into shadow-aligned coordinates to form an oriented bounding box, and tests every road segment against that box. Each hit contributes 60 minutes to the segment's accumulated shadow.

The output replaces the roads layer in the array; every road feature now carries `properties.compute.shadow` (minutes).

```javascript
function getRing(feature) {
    let g = feature.geometry;
    if (g.type === 'GeometryCollection') {
        g = g.geometries.find(x => x.type === 'Polygon' || x.type === 'MultiPolygon');
    }
    if (!g) return null;
    if (g.type === 'Polygon') return g.coordinates[0];
    if (g.type === 'MultiPolygon') return g.coordinates[0][0];
    return null;
}

const buildings = arg.find(l => l.name === 'table_osm_buildings').geojson;
const roads     = arg.find(l => l.name === 'table_osm_roads').geojson;

const feature = buildings.features[0];
const footprint = getRing(feature);
const height = parseFloat(feature.properties?.height) || 30;

const SHADOW_WGSL = `
let pi      = 3.14159265359;
let lat_rad = 0.73027;
let lon_ref = -75.0;
let lon_loc = -87.65;

let dec_rad = -0.40928 * cos(2.0 * pi / 365.0 * (doy + 10.0));
// ... project the building ring into shadow-aligned coords,
//     form an OBB, and test each road segment against it.
out[0] = accumulated;
return out;
`;

const compute = new ComputeGpgpu();
const computedRoads = await compute.run({
    collection: roads,
    variableMapping: { seg: 'geometry.coordinates' },
    attributeMatrices: { seg: { rows: 'auto', cols: 2 } },
    uniforms: { bld_height: height, doy: 172 },
    uniformMatrices: { ring: { data: footprint, cols: 2 } },
    outputColumns: ['shadow'],
    wgslBody: SHADOW_WGSL,
});

return arg.map(l => l.name === 'table_osm_roads' ? { ...l, geojson: computedRoads } : l);
```

The full WGSL body in the seeded example contains the OBB intersection logic — the snippet above abbreviates it. `doy: 172` is the day-of-year for the June solstice; change it to `265` for September or `355` for December.

## Step 3: Filter to the shadowed subset (`AUTK_COMPUTE`)

A separate node trims the roads layer down to only the segments whose `compute.shadow > 0`. We keep this as its own node because it is a real data transformation, and because the **map** and **histogram** want different shapes of the same upstream data — making the fork explicit in the graph is clearer than burying a `.filter()` inside the plot node.

```javascript
const ROADS_LAYER = 'table_osm_roads';
const roads = arg.find(l => l.name === ROADS_LAYER).geojson;

const shaded = {
    type: 'FeatureCollection',
    features: roads.features.filter(f => (f.properties?.compute?.shadow ?? 0) > 0),
};

return arg.map(l => l.name === ROADS_LAYER ? { ...l, geojson: shaded } : l);
```

## Step 4: Thematic map (`AUTK_MAP`)

The map node consumes the **full** layer array straight from `shadow-shader` and colours every road by `properties.compute.shadow`. Unshaded roads paint at the low end of the colour ramp, so the user still sees them as context around the building's shadow path.

```javascript
const map = new AutkMap(container);
await map.init();
for (const layer of arg) {
    map.loadCollection(layer.name, { collection: layer.geojson, type: layer.type });
}
map.updateRenderInfo('table_osm_roads', { isPick: true, isColorMap: true });
map.updateThematic('table_osm_roads', {
    collection: arg.find(l => l.name === 'table_osm_roads').geojson,
    property: 'properties.compute.shadow',
});
map.draw();
return map;
```

## Step 5: Brushable histogram (`AUTK_PLOT`)

The histogram consumes the **filtered** layer array from `shadow-shaded-roads`, so the bins describe the distribution across roads the building actually shadowed. Brushing the chart highlights matching segments on the map via the Interaction edge.

```javascript
const roads = arg.find(l => l.name === 'table_osm_roads')?.geojson ?? arg[0]?.geojson;
return new AutkPlot(container, {
    type: 'barchart',
    collection: roads,
    attributes: { axis: ['compute.shadow', '@transform'] },
    labels: { axis: ['Minutes of shadow', '#Shaded road segments'], title: 'Shadow distribution' },
    width: 600,
    height: 380,
    events: ['brushX'],
    transform: { preset: 'binning-1d', options: { bins: 13 } },
});
```

## Going further

The minimal version above keeps things linear so the GPU shader stays the focus. The upstream Autark example layers on more capability — picking-driven recompute against any clicked building, monthly variants, and ground-truth baselines from a CSV — and is a good next step once the basics are clear: see [main.ts](https://github.com/urban-toolkit/autark/blob/main/usecases/src/shadows/main.ts) and [shadow.wgsl](https://github.com/urban-toolkit/autark/blob/main/usecases/src/shadows/shadow.wgsl) upstream.
