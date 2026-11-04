# `model.scout.deep-umbra@1`: Deep Umbra (accumulated shadows)

SCOUT's accumulated shadow simulation, ported from
[SCOUT](https://github.com/urban-toolkit/scout)
(`backend/compute/accumulated_shadow_simulation`). Deep Umbra, SCOUT's shadow
model, predicts how much of a season's day the ground spends in shadow, from the
height raster of Rasterize Buildings, a node of [Scout](../curio.scout@1/README.md).

This is a model package: its weights, its node and the module the node imports.
The [Model Catalog](../../docs/MODEL-CATALOG.md) lists it.

| Part | What it is | License |
|---|---|---|
| `models/deep_umbra.onnx` | Deep Umbra's weights | Used with the permission of SCOUT's authors, published by SCOUT (urban-toolkit/scout) |
| `sources/accumulated-shadow.py` | The Accumulated Shadow node's cell | MIT |
| `sources/deep_umbra/` | The module the cell imports: `node_outputs.py` (the node's input and output) and `deep_umbra.py` (SCOUT's functions) | MIT |

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `model.scout.deep-umbra/accumulated-shadow` | Accumulated Shadow | The height raster of Rasterize Buildings; a second circle takes a VALUE, such as a season a node wired into it returns | One RASTER: the accumulated shadow in minutes |

The node's cell:

```python
from deep_umbra import accumulated_shadow
model = curio_load_model("model.scout.deep-umbra")
return accumulated_shadow(input_0, season=[!! season !!], model=model, output_file=curio_output_file)
```

## Settings

The node's **Widgets** tab holds its setting:

| Widget | Default | What it sets |
|---|---|---|
| Season (`season`) | `summer` | spring, summer or winter: the season's sun, and the minutes a day of shadow counts for (540, 720 and 360) |

A season several Accumulated Shadow nodes share comes from one node that
returns it, wired into each one's second circle, whose code then reads
`season=input_1` in place of `[!! season !!]`, as the scenarios of the
[Chicago Loop shadow](../../docs/examples/dataflows/chicago-loop-shadow-towers.json)
test dataflow do.

The input is a raster of building heights in metres in EPSG:3395 (World
Mercator) on the zoom-16 tile grid, 256 cells a tile: Rasterize Buildings'
raster at its defaults. Deep Umbra reads heights where 255 is 550 m, so the node
refuses a raster at another zoom level, off the tile grid, or drawn with another
maximum height.

## Output

The accumulated shadow of every tile of the input that holds heights, on the
input's own grid, one band in minutes. A tile with no data, a tile SCOUT wrote
no file for, gets no shadow, as in SCOUT. An Autark map draws it as `input_0`:

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
```

SCOUT's metrics, the mean and median accumulated shadow over the ground, come
from the statistics of a **Raster Calculator** node (`curio.scout@1`): the
shadow on its input_0, the heights on its input_1 as the mask, and the ground
where Deep Umbra reads gray level 0, a height under 1.08 m:

```python
from scout_rasters.raster_algebra import raster_statistics

return raster_statistics(input_0, mask=input_1, where=lambda height: height < 1.08)
```

The ground counted is the ground of the tiles with heights only, as in SCOUT's
metrics. Deep Umbra predicts each tile from the tile and its eight neighbours,
so a tile at the edge of the raster, or beside a tile with no data, sees no
buildings there.

## The model

Deep Umbra's weights are an ONNX file exported from SCOUT's TensorFlow
checkpoint by
[`scripts/scout/export_deep_umbra.py`](../../scripts/scout/export_deep_umbra.py).
The node loads them with `curio_load_model("model.scout.deep-umbra")` and runs
them with onnxruntime, one tile at a time.

A pip install downloads the weights from GitHub the first time the node runs.

## A dataflow

```
[ Buildings ] ──► [ Rasterize Buildings ] ──► [ Accumulated Shadow ] ──► [ Autark: map of the shadow ]
                            │                          │
                            └──── mask ──► [ Raster Calculator ] ◄──┘
```

[Example 24](../../docs/examples/24-scout-shadow-model-chicago-loop.md) maps the shadow
of SCOUT's Chicago Loop buildings. The test dataflow
[Chicago Loop shadow with towers removed or edited](../../docs/examples/dataflows/chicago-loop-shadow-towers.json) compares SCOUT's
two building sets of the Chicago Loop as two scenarios, each with a map of its
shadow: the buildings as they are, and with 15 of them removed.

## Setup

Curio installs the package's Python libraries with it: `onnxruntime`,
`rasterio`, `numpy` and `pyproj`. It is installed for you when Curio starts
with `--with-examples`.

The package depends on [Scout](../curio.scout@1/README.md) (`curio.scout@1`
in its `dependencies.packages`): the node places each tile it predicts with
Scout's `tile_bounds` (`scout_rasters.web_tiles`), so Scout must be installed
too, and a run of the node is handed both packages' modules.
