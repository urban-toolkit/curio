# `scout.shadow-simulation@1`: SCOUT Shadow Simulation

SCOUT's accumulated shadow simulation, ported from
[SCOUT](https://github.com/urban-toolkit/scout) (`backend/models/shadow`).
It runs [Deep Umbra](https://github.com/uic-evl/deep-umbra), a generative
model of sunlight access, on the building-height tiles Rasterize Buildings
(`scout.raster-conversion@1`) makes, and gives the minutes of the day the
ground is in shadow.

The model is not in this package. It is `model.scout.deep-umbra` in the
[Model Catalog](../../docs/MODEL-CATALOG.md), and the node's code names it:

```python
model = curio_load_model("model.scout.deep-umbra")
```

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.shadow-simulation/simulate-shadows` | Simulate Shadows | Rasterize Buildings' `(mosaic, tiles)` | `(mosaic, tiles, summary)`: one RASTER and two tables |

## Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Season (`season`) | `summer` | `spring`, `summer` or `winter`, as SCOUT offers them |

Deep Umbra was trained on zoom-16 tiles where gray level 255 is 550 m, the
defaults of Rasterize Buildings. The node stops with a message that says what
to set when its tiles were made otherwise.

## What it does

For each tile, as SCOUT's `predict_shadow` does: the tile and half of each of
its eight neighbours make a 512 by 512 window (a missing neighbour is ground),
with planes for the tile's latitude and the season. Deep Umbra draws the
window's shadow, and the 256 by 256 middle is the tile's. Its value from -1 to
1 becomes a share of the day, 0 to 1, times the minutes SCOUT counts for the
season: 360 in winter, 540 in spring, 720 in summer.

## Outputs

- **mosaic**: the tiles' shadows side by side, on the grid of Rasterize
  Buildings' mosaic (EPSG:3395): one band, the minutes of the day each cell is
  in shadow. A tile with no building near it is 0. An Autark map draws it as
  `input_0`:

  ```json
  {"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
  ```

- **tiles**: one row per tile, with `zoom`, `x`, `y`, `png`, the tile's
  shadow as SCOUT writes it (8-bit gray, 255 is shadow all day, in base64),
  and `mean_shadow_min`, the mean over the tile's ground.
- **summary**: one row, SCOUT's metrics: `Mean Acc shadow` and
  `Median Acc shadow`, in minutes, over the ground of every tile (the pixels
  with no building), and the `season`.

## A dataflow

```
[ Data Loading: buildings ] ──► [ Rasterize Buildings ] ──► [ Simulate Shadows ] ──► [ Autark: map of the shadows ]
```

## Setup

Curio installs the package's Python libraries with it: `onnxruntime` and
`rasterio`. Deep Umbra ships with Curio in the Model Catalog.
