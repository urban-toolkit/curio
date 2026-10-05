"""Accumulated Shadow: SCOUT's Deep Umbra shadow model.

Input: the height mosaic of Rasterize Buildings (scout.raster-conversion), or
its (mosaic, tiles) output: building heights in metres in EPSG:3395 on the
zoom-16 tile grid.
Output: the accumulated shadow in minutes, a raster on the input's grid. An
Autark map draws it as input_0, band band_1. A Raster Statistics node gives its
mean and median over the ground: the heights on its input 1 as the mask, with
where=lambda height: height < 1.08.
The Widgets tab sets the season. The model is the Data Catalog dataset
data.scout.deep-umbra.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_shadow.node_outputs import accumulated_shadow, open_model

model = open_model(lambda: curio_load_data("data.scout.deep-umbra"))
return accumulated_shadow(arg, season=[!! season !!], model=model, output_file=curio_output_file)
