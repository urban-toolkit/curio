# Example: What-if shadow study with Autark

In this example we walk through a what-if dataflow that flags "tall" buildings in Boston's Back Bay
(footprint area > 200 m²), raises their heights by a fixed multiplier, and renders the modified scenario
side-by-side with the baseline. Two `autk-grammar` nodes load the same local PBF independently — one
renders the baseline, the other applies the criterion on the GPU and renders the modified scenario.
Building **height** is the what-if proxy that's directly visible on the rendered map.

> [!NOTE]
> **WebGPU required**
> Autark relies on WebGPU. Run this example in a Chromium-based browser (Chrome / Edge) on a machine
> with a working GPU stack. `navigator.gpu` must be available.

## Pipeline overview

```mermaid
flowchart LR
  B["baseline · autk-grammar<br/>data → map by height"]
  M["modified · autk-grammar<br/>data → compute area → map by height_mod"]
```

The two nodes are independent (no edge): each loads `back_bay.osm.pbf` and renders its own map, so you can
place the baseline and modified scenarios side by side and compare.

## Data

`docs/examples/data/back_bay.osm.pbf` — OSM extract for Boston's Back Bay (regenerate with
`scripts/build_example_pbfs.py`).

## Step 1: Load physical layers from a PBF (`data`)

Both nodes share the same `data` block. It loads Back Bay's buildings, surface, and parks from the local
PBF — DuckDB-WASM parses it in the browser, so there's no Overpass call at run time. autk-db materializes
the layers in EPSG:3395 (metric), which is what the footprint-area math in Step 2 assumes.

```json
"data": [{
  "type": "osm",
  "pbfFileUrl": "docs/examples/data/back_bay.osm.pbf",
  "queryArea": { "geocodeArea": "Boston", "areas": ["Back Bay"] },
  "outputTableName": "table_osm",
  "autoLoadLayers": { "layers": ["surface", "parks", "buildings"], "dropOsmTable": true }
}]
```

## Step 2: GPU footprint-area criterion + multiplier (`compute`, modified node only)

The modified node's `compute` block binds each building's **outer ring** as a per-feature matrix
(`attributes.ring` = `geometry.coordinates.0`, `attributeMatrices.ring`) and the `height` attribute, then
runs a WGSL shoelace sum to get the footprint **area** in m². Buildings over 200 m² get `height × 3`;
everything else keeps its height. The result is written to the `height_mod` output column.

```json
"compute": [{
  "dataRef": "table_osm_buildings",
  "attributes": { "ring": "geometry.coordinates.0", "h": "height" },
  "attributeMatrices": { "ring": { "rows": "auto", "cols": 2 } },
  "outputColumnName": "height_mod",
  "wglsFunction": "... shoelace area over the ring; if area > 200 return h*3 else h ..."
}]
```

The WGSL walks the ring vertices (`ring[i*2]`, `ring[i*2+1]`) accumulating the signed cross-products, halves
the absolute sum for the area, and applies the multiplier. The full body lives in the example JSON.

## Step 3: Baseline vs modified maps (`map`)

The **baseline** node colours buildings by their original `height`; the **modified** node colours by
`compute.height_mod`. Surface and parks render underneath for context. Side-by-side, the raised buildings
stand out.

```json
// baseline node
"map": { "layerRefs": [
  { "dataRef": "table_osm_surface" },
  { "dataRef": "table_osm_parks" },
  { "dataRef": "table_osm_buildings", "getFnv": "height", "getFnvType": "quantitative", "defaultFnv": 10 }
]}

// modified node — same, but coloured by the computed column
{ "dataRef": "table_osm_buildings", "getFnv": "compute.height_mod", "getFnvType": "quantitative", "defaultFnv": 10 }
```

## Final result

Two maps of Back Bay: the baseline coloured by original height and the modified scenario with footprints
larger than 200 m² raised 3×. Swap the multiplier in the WGSL, or replace the area criterion with the
WGSL shadow shader from [Example 7](07-autark-gpu-shader.md), to explore other what-ifs.
