# `scout.shadow@1`: SCOUT Shadow

SCOUT's accumulated shadow simulation, ported from
[SCOUT](https://github.com/urban-toolkit/scout)
(`backend/compute/accumulated_shadow_simulation`). Deep Umbra, SCOUT's shadow
model, predicts how much of a season's day the ground spends in shadow, from the
height tiles of [SCOUT Raster Conversion](../scout.raster-conversion@1/README.md).

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.shadow/accumulated-shadow` | Accumulated Shadow | The `(mosaic, tiles)` output of Rasterize Buildings, or its tiles table | `(mosaic, metrics)`: one RASTER and one table |

## Settings

The node's **Widgets** tab holds its setting:

| Widget | Default | What it sets |
|---|---|---|
| Season (`season`) | `summer` | spring, summer or winter: the season's sun, and the minutes a day of shadow counts for (540, 720 and 360) |

Deep Umbra reads zoom-16 tiles where 255 is 550 m, Rasterize Buildings' defaults;
the node refuses tiles drawn at another zoom level or maximum height.

## Outputs

- **mosaic**: the accumulated shadow of every tile, side by side in one GeoTIFF in
  EPSG:3395 (World Mercator) on the tiles' own grid, one band in minutes. Places
  no tile covers are nodata. An Autark map draws it as `input_0`:

  ```json
  {"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
  ```

- **metrics**: one row: `season`, and `mean_minutes` and `median_minutes`, the mean
  and median accumulated shadow over the ground of every tile (its pixels with no
  building), as SCOUT reports them.

Deep Umbra predicts each tile from the tile and its eight neighbours, so a tile
at the edge of the area sees no buildings beyond it.

## The model

The model is the Data Catalog dataset `data.scout.deep-umbra@1`, an ONNX file
exported from SCOUT's TensorFlow checkpoint by
[`scripts/scout/export_deep_umbra.py`](../../scripts/scout/export_deep_umbra.py).
The node reads it with `curio_load_data("data.scout.deep-umbra")` and runs it with
onnxruntime, one tile at a time.

The model ships in the Curio repository but not in the pip package. On a pip
install the node says so: copy the repository's folder
`datasets/data.scout.deep-umbra@1` into the shared Data Catalog folder (the one
`--catalog-root` names, else the `datasets` folder beside the installed
`utk_curio` package), then run the node again.

## A dataflow

```
[ Buildings ] ──► [ Rasterize Buildings ] ──► [ Accumulated Shadow ] ──► [ Autark: map of the mosaic ]
```

The test dataflow [ScoutShadows](../../docs/examples/dataflows/ScoutShadows.json)
compares SCOUT's two building sets of the Chicago Loop as two scenarios: the
buildings as they are, and with 15 of them removed.

## Setup

Curio installs the package's Python libraries with it: `onnxruntime` and
`rasterio`. It is installed for you when Curio starts with `--with-examples`.
