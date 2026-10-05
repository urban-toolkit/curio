# `scout.shadow@1`: SCOUT Shadow

SCOUT's accumulated shadow simulation, ported from
[SCOUT](https://github.com/urban-toolkit/scout)
(`backend/compute/accumulated_shadow_simulation`). Deep Umbra, SCOUT's shadow
model, predicts how much of a season's day the ground spends in shadow, from the
height mosaic of [SCOUT Raster Conversion](../scout.raster-conversion@1/README.md).

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.shadow/accumulated-shadow` | Accumulated Shadow | The height mosaic of Rasterize Buildings, or its `(mosaic, tiles)` output | One RASTER: the accumulated shadow in minutes |

## Settings

The node's **Widgets** tab holds its setting:

| Widget | Default | What it sets |
|---|---|---|
| Season (`season`) | `summer` | spring, summer or winter: the season's sun, and the minutes a day of shadow counts for (540, 720 and 360) |

The input is a raster of building heights in metres in EPSG:3395 (World
Mercator) on the zoom-16 tile grid, 256 cells a tile: Rasterize Buildings'
mosaic at its defaults. Deep Umbra reads heights where 255 is 550 m, so the node
refuses a raster at another zoom level, off the tile grid, or drawn with another
maximum height.

## Output

The accumulated shadow of every tile of the input, on the input's own grid, one
band in minutes. An Autark map draws it as `input_0`:

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
```

SCOUT's metrics, the mean and median accumulated shadow over the ground, come
from a **Raster Statistics** node (`curio.builtin@1`): the shadow on its input 0,
the heights on its input 1 as the mask, and the ground where Deep Umbra reads
gray level 0, a height under 1.08 m:

```python
return curio_raster_statistics(arg, where=lambda height: height < 1.08)
```

Deep Umbra predicts each tile from the tile and its eight neighbours, so a tile
at the edge of the raster sees no buildings beyond it.

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
[ Buildings ] ──► [ Rasterize Buildings ] ──► [ Height mosaic ] ──► [ Accumulated Shadow ] ──► [ Autark: map of the shadow ]
                                                    │                        │
                                                    └──── mask ──► [ Raster Statistics ] ◄──┘
```

The Height mosaic node is a Python node that keeps the mosaic of Rasterize
Buildings' `(mosaic, tiles)` (`return arg[0]`), since Raster Statistics reads
rasters only.

The test dataflow [ScoutShadows](../../docs/examples/dataflows/ScoutShadows.json)
compares SCOUT's two building sets of the Chicago Loop as two scenarios: the
buildings as they are, and with 15 of them removed.

## Setup

Curio installs the package's Python libraries with it: `onnxruntime` and
`rasterio`. It is installed for you when Curio starts with `--with-examples`.
