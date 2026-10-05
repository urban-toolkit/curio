"""Simulate Shadows: SCOUT's accumulated shadow simulation, with Deep Umbra.

Input: Rasterize Buildings' output, (mosaic, tiles), made at zoom 16 with a
maximum height of 550 m, the tiles Deep Umbra was trained on.
Output: (mosaic, tiles, summary).
- mosaic: one raster on the buildings mosaic's grid, each cell the minutes
  of the day it is in shadow. An Autark map draws it as input_0, band band_1.
- tiles: one row per map tile, with zoom, x, y, png, the 8-bit grayscale
  PNG (base64) of its shadow, where 255 is shadow all day, and
  mean_shadow_min, the mean over the ground around its buildings.
- summary: one row, SCOUT's metrics: Mean Acc shadow and Median Acc shadow
  over the ground, in minutes.
The Widgets tab sets the season. To use another model, drag it from the
Model Catalog onto this node.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_shadow_simulation.node_outputs import simulate_shadows

model = curio_load_model("model.scout.deep-umbra")

return simulate_shadows(
    arg,
    model,
    season=[!! season !!],
    output_file=curio_output_file,
)
