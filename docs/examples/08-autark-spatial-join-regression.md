# Example: Per-feature spatial join + GPU regression with Autark

This example combines OSM road geometry with a 24-band land-surface-temperature (LST) raster to estimate
the per-road warming trend over Niterói (2001–2024). It mixes the Autark grammar with imperative JS/Python
nodes: an `autk-grammar` **data** node loads roads from a local PBF, a Python node fetches the raster, a JS
DuckDB node spatially joins per-band LST averages onto each road, and a second `autk-grammar` node fits a
per-feature OLS regression on the GPU and feeds a thematic map + brushable scatter linked through a Data Pool.

It is a Curio port of the upstream Autark use case at
[github.com/urban-toolkit/autark/tree/main/usecases/src/niteroi](https://github.com/urban-toolkit/autark/tree/main/usecases/src/niteroi).

> [!NOTE]
> **WebGPU required**
> Autark relies on WebGPU. Run this example in a Chromium-based browser (Chrome / Edge) on a machine
> with a working GPU stack.

> [!NOTE]
> **Network access required**
> Step 2 downloads a 24-band GeoTIFF (~10 MB) from
> `https://raw.githubusercontent.com/urban-toolkit/autark/main/usecases/public/data/niteroi_lst_verao_2001_2024.tif`.
> It must be reachable when the dataflow runs.

## Pipeline overview

```mermaid
flowchart LR
  OSM[autk-grammar data<br/>Niterói OSM PBF] --> MERGE[merge-flow]
  RASTER[data-loading<br/>24-band LST GeoTIFF] --> MERGE
  MERGE --> JOIN[js-computation<br/>DuckDB raster spatial join]
  JOIN --> OLS[autk-grammar<br/>OLS regression]
  OLS --> POOL[data-pool]
  POOL --> MAP[autk-grammar<br/>thematic 3D map]
  POOL --> PLOT[autk-grammar<br/>brushable scatter]
  POOL <-. brush/pick .-> MAP
  POOL <-. brush/pick .-> PLOT
```

The one step the grammar can't express — sampling a raster — stays in a JS DuckDB node; the regression and
the linked views live in the grammar, and the Data Pool fans the result out to both views and routes brush
selections back.

## Data

`docs/examples/data/niteroi.osm.pbf` — OSM extract for Niterói (regenerate with
`scripts/build_example_pbfs.py`). The 24-band LST raster is fetched at run time from the upstream Autark
repo (Step 2).

## Step 1: Load OSM layers from a PBF (`autk-grammar`, data block)

A grammar node with only a `data` block loads Niterói's surface, parks, water, and roads from the local PBF.
Layers are emitted in **EPSG:4326** so the downstream join node can re-ingest them via `loadCustomLayer`
(which assumes WGS84 input) and reproject to a metric CRS for the spatial join — setting
`autoLoadLayers.coordinateFormat` to `EPSG:4326` is what keeps that contract (the grammar default is the
metric `EPSG:3395`).

```json
"data": [{
  "type": "osm",
  "pbfFileUrl": "docs/examples/data/niteroi.osm.pbf",
  "queryArea": { "geocodeArea": "Rio de Janeiro", "areas": ["Niterói"] },
  "outputTableName": "table_osm",
  "autoLoadLayers": { "coordinateFormat": "EPSG:4326", "dropOsmTable": true, "layers": ["surface", "parks", "water", "roads"] }
}]
```

The data-only grammar node persists the layer array (`table_osm_surface` / `_parks` / `_water` / `_roads`)
to the backend and emits a DuckDB reference. The downstream `js-computation` join receives it as the plain
`[{ name, type, geojson }]` array — the Curio sandbox resolves the reference automatically before the join's
`arg` is built, so no manual fetch is needed. Downstream autark nodes reference these layers by name
(`"dataRef": "table_osm_roads"`) — the named-layer case of
[Referencing Upstream Data in Autark Nodes](../ARCHITECTURE.md#referencing-upstream-data-in-autark-nodes).

## Step 2: Reference the LST raster (`data-loading`)

A Python node fetches the 24-band LST GeoTIFF once and embeds the bytes as base64 inside a single-row
GeoDataFrame, so the join node can reuse them without a second HTTP request.

```python
import base64, requests, geopandas as gpd
from shapely.geometry import Point

url = 'https://raw.githubusercontent.com/urban-toolkit/autark/main/usecases/public/data/niteroi_lst_verao_2001_2024.tif'
resp = requests.get(url, timeout=120); resp.raise_for_status()
geotiff_b64 = base64.b64encode(resp.content).decode('ascii')
return gpd.GeoDataFrame({'geotiff_b64': [geotiff_b64], 'band_count': [24]}, geometry=[Point(0, 0)], crs='EPSG:4326')
```

The two branches are bundled by a **`merge-flow`** node into a 2-element input — `arg[0]` is the OSM layer
array, `arg[1]` is the raster row.

## Step 3: Spatial join LST → roads (`js-computation`, DuckDB)

The join node re-ingests each OSM layer into DuckDB (reprojecting to EPSG:3395), loads the raster with
`loadGeoTiff`, and runs a `NEAR` `spatialQuery` to average each of the 24 bands within 1 km of every road
segment. A final `rawQuery` reshapes the per-band averages into a single `lst_timeseries` array per road and
re-emits the layer stack (all in EPSG:3395) for a consistent CRS across surface/parks/water/roads.

```js
for (const layer of osmLayers)
  await db.loadCustomLayer({ geojsonObject: layer.geojson, outputTableName: layer.name, coordinateFormat: 'EPSG:3395', layerType: layer.type });
await db.loadGeoTiff({ geotiffArrayBuffer, outputTableName: 'lst', sourceCrs: 'EPSG:4326', coordinateFormat: 'EPSG:3395' });
await db.spatialQuery({
  tableRootName: 'table_osm_roads', tableJoinName: 'lst', spatialPredicate: 'NEAR', nearDistance: 1000,
  output: { type: 'MODIFY_ROOT' }, joinType: 'LEFT',
  groupBy: { selectColumns: Array.from({ length: 24 }, (_, i) => ({ tableName: 'lst', column: `band_${i + 1}`, aggregateFn: 'avg', aggregateFnResultColumnName: `band_${i + 1}` })) },
});
// … rawQuery packs the 24 band averages into properties.lst_timeseries …
```

## Step 4: Per-road OLS regression (`autk-grammar`)

The grammar `compute` block binds each road's 24-year series as a per-feature array
(`attributes.bands` = `lst_timeseries`, `attributeArrays.bands` = 24) and runs the OLS WGSL shader, emitting
two columns — `angle` (warming angle, degrees) and `intercept`. It references the roads layer by its real
name so the surface/parks/water context layers pass through untouched.

```json
"compute": [{
  "dataRef": "table_osm_roads",
  "attributes": { "bands": "lst_timeseries" },
  "attributeArrays": { "bands": 24 },
  "outputColumns": ["angle", "intercept"],
  "wglsFunction": "... OLS slope/intercept over the 24 bands; angle = atan(slope) in degrees ..."
}]
```

## Step 5: Linked map + scatter through a Data Pool

The compute output flows into a **`data-pool`** node, which fans the augmented layer stack out to two
`autk-grammar` views and routes brush/pick selections between them (`Interaction` edges `pool→map` and
`pool→plot`). The `map` renders the full stack and colours roads by `angle`; the `plot` is a brushable
`intercept`-vs-`angle` scatter — brushing it highlights the matching roads on the 3D map.

```json
"map": { "layerRefs": [
  { "dataRef": "table_osm_surface" }, { "dataRef": "table_osm_parks" }, { "dataRef": "table_osm_water" },
  { "dataRef": "table_osm_roads", "isPick": true, "isColorMap": true, "getFnv": "angle", "getFnvType": "quantitative", "defaultFnv": 0 }
]}

"plot": { "dataRef": "table_osm_roads", "mark": "scatter", "axis": ["intercept", "angle"],
          "title": "LST regression — warming angle vs baseline (Niterói roads)", "events": ["brush"] }
```

## Going further

The upstream Autark use case adds per-month variants and a richer raster pipeline; see
[github.com/urban-toolkit/autark/tree/main/usecases/src/niteroi](https://github.com/urban-toolkit/autark/tree/main/usecases/src/niteroi).
