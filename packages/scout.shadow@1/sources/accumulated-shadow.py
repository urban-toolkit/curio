"""Accumulated Shadow: SCOUT's Deep Umbra shadow model.

Input: the tiles of Rasterize Buildings (scout.raster-conversion), its
(mosaic, tiles) output or the tiles table alone: zoom-16 tiles where 255 is
550 m.
Output: (mosaic, metrics).
- mosaic: one raster in EPSG:3395, each cell the accumulated shadow in minutes.
  An Autark map draws it as input_0, band band_1.
- metrics: one row, the season and the mean and median accumulated shadow in
  minutes over the ground (pixels with no building).
The Widgets tab sets the season. The model is the Data Catalog dataset
data.scout.deep-umbra.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_shadow.node_outputs import accumulated_shadow, open_model

model = open_model(lambda: curio_load_data("data.scout.deep-umbra"))
return accumulated_shadow(arg, season=[!! season !!], model=model, output_file=curio_output_file)
