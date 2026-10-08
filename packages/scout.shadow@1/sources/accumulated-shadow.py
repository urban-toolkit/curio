"""Accumulated Shadow: SCOUT's Deep Umbra shadow model.

Input: Rasterize Buildings' table of tiles (scout.raster-conversion). The
height tiles themselves are this dataflow's computed dataset the "Tiles"
widget names, the name Rasterize Buildings saved them under ("tiles").
Output: (shadow, metrics).
- shadow: the accumulated shadow in minutes, one raster in EPSG:3395 on the
  grid of the tiles' height mosaic (Mosaic Tiles), made from the shadow tiles
  SCOUT's run_shadow_model writes. An Autark map draws it, band band_1.
- metrics: SCOUT's metrics as its run_shadow_model computes them, one row:
  "Mean Acc shadow" and "Median Acc shadow", the minutes of shadow over the
  ground (the cells with no building), for Compare Scenarios.
The shadow tiles are kept as a computed dataset of this dataflow, under the
name the "Save shadows as" widget gives.
The Widgets tab sets the season and the names. The model is the Model
Catalog's Deep Umbra, model.scout.deep-umbra, its ONNX file run as it is.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_shadow.deep_umbra import run_shadow_model
from scout_shadow.mosaic import mosaic

shadows = curio_save_folder([!! shadows !!])
metrics = run_shadow_model(
    curio_computed_path([!! tiles !!]),
    [!! season !!],
    shadows,
    model_path=curio_load_model("model.scout.deep-umbra").entry,
)
return mosaic(shadows, [!! season !!], curio_output_file), metrics
