# `scout.shadow@1`: SCOUT Shadow

SCOUT's accumulated shadow simulation, ported from
[SCOUT](https://github.com/urban-toolkit/scout)
(`backend/compute/accumulated_shadow_simulation`). Deep Umbra, SCOUT's shadow
model, predicts how much of a season's day the ground spends in shadow, from the
height tiles [SCOUT Raster Conversion](../scout.raster-conversion@1/README.md)'s
Rasterize Buildings saves in the dataflow.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.shadow/accumulated-shadow` | Accumulated Shadow | Rasterize Buildings' table of tiles (`scout.raster-conversion@1`); the tiles themselves are read from the dataflow SCOUT's shadow tiles, saved in the dataflow; `(shadow, metrics)`: a RASTER of the accumulated shadow in minutes and SCOUT's metrics, a DATAFRAME |

## Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Season (`season`) | `summer` | spring, summer or winter: the season's sun, and the minutes a day of shadow counts for (540, 720 and 360) |
| Tiles (`tiles`) | `tiles` | The name the height tiles were saved under, Rasterize Buildings' **Save tiles as** |
| Save shadows as (`shadows`) | `shadows` | The name SCOUT's shadow tiles are kept under |

Two Accumulated Shadow nodes in one dataflow, as in two scenarios, each need
names of their own.

## SCOUT's code

`sources/scout_shadow/deep_umbra.py` is SCOUT's
`backend/compute/accumulated_shadow_simulation/scripts/deep_umbra.py` (commit
`b98369e5`) as SCOUT wrote it, with these changes, each marked `# Curio:`:

- TensorFlow's calls are numpy's and OpenCV's, one for one: `tf.math` in
  `num2deg` (in float32, as TensorFlow computes it), `tf.io` reading the tiles
  in `load_input`, `tf.zeros`, `tf.tensor_scatter_nd_update`, `tf.ones` and
  `tf.math.scalar_mul` in `load_input_grid`.
- The generator is the exported ONNX graph, run with onnxruntime:
  `get_deep_shadow(model_path)` opens an `InferenceSession` on it where SCOUT
  builds the network and restores its checkpoint, and `predict_shadow` runs it
  where SCOUT calls the generator with `training=True` (the graph keeps that
  mode's batch normalization).
- The training code (the losses, the generator and discriminator
  architectures, `DeepShadow`) and the unused imports are left out.
- `run_shadow_model` takes `model_path`; it does not make or empty its output
  folder, which `curio_save_folder` gives it empty; and it returns its metrics
  table where SCOUT saves it as a CSV under `metrics_out`, which it does not
  take.

On SCOUT's committed height tiles its shadow tiles are SCOUT's committed ones
within a few gray levels on a few percent of pixels, and its metrics within a
tenth of a minute (the tests explain the bound: Deep Umbra's float32 output
depends on the order of its sums).

The node reads the height tiles with `curio_computed_path`, hands
`run_shadow_model` the folder `curio_save_folder` gives for the shadow tiles, and
returns a tuple: `mosaic` of the shadow tiles, and the metrics `run_shadow_model`
returns.

## Output

The node returns `(shadow, metrics)`, so the node after it reads the raster as
`input_0[0]` and the metrics as `input_0[1]`.

`sources/scout_shadow/mosaic.py`, Curio's own code, puts SCOUT's shadow tiles
side by side in one GeoTIFF in EPSG:3395, each where SCOUT's rasterizer drew the
heights it was predicted from, so it shares the height mosaic's grid. One band
in minutes: a tile's gray level times the season's minutes over 255 (steps of
2.8 minutes in summer). A cell no tile covers has no value. An Autark map draws
it as `input_0`:

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
```

The metrics are SCOUT's own, one row with `Mean Acc shadow` and
`Median Acc shadow`: the minutes of shadow over the ground (the cells with no
building), computed by `run_shadow_model` from Deep Umbra's predictions before
they are written as 8-bit tiles. A **Compare Scenarios** node charts them side
by side.

Deep Umbra predicts each tile from the tile and its eight neighbours, so a tile
at the edge sees no buildings beyond it.

## The model

The model is Deep Umbra in the [Model Catalog](../../docs/MODEL-CATALOG.md),
`model.scout.deep-umbra@1`, an ONNX file exported from SCOUT's TensorFlow
checkpoint by
[`scripts/scout/export_deep_umbra.py`](../../scripts/scout/export_deep_umbra.py).
The node gets the file's path with `curio_load_model("model.scout.deep-umbra").entry`
and SCOUT's code runs it with onnxruntime, one tile at a time.

A pip install downloads the model from GitHub the first time the node runs.

## A dataflow

```
[ Buildings ] ──► [ Rasterize Buildings ] ──► [ Accumulated Shadow ] ──► input_0[0] ──► [ Autark: map of the shadow ]
                            │                          │
                            ▼                          └──────────► input_0[1] ──► [ Compare Scenarios ]
                     [ Mosaic Tiles ] ──► [ Autark: map of the heights ]
```

Rasterize Buildings saves SCOUT's height tiles in the dataflow. Accumulated
Shadow reads them by their name, and Mosaic Tiles joins them into the height
mosaic, on the same grid as the shadow.

[Example 24](../../docs/examples/24-scout-building-rasters.md) maps the shadow
of SCOUT's Chicago Loop buildings. The test dataflow
[ScoutShadows](../../docs/examples/dataflows/ScoutShadows.json) compares SCOUT's
two building sets of the Chicago Loop as two scenarios: the buildings as they
are, and with 15 of them removed.

## Setup

Curio installs the package's Python libraries with it: `onnxruntime`,
`rasterio`, `opencv-python-headless`, `pandas` and `pyproj`. It is installed
for you when Curio starts with `--with-examples`.
