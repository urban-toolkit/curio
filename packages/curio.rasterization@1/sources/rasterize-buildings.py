"""Rasterize Buildings: SCOUT's building rasterizer, "OSM vector to raster".

Input: a buildings layer, a GeoDataFrame of polygons with a CRS and a column
of heights in metres.
Output: one raster in EPSG:3395, each cell a height in metres: the 256 by 256
map tiles SCOUT draws, 8-bit gray where 255 is the maximum height, side by
side. A tile SCOUT writes no file for, because no building is near it, is no
data. An Autark map draws it as input_0, band band_1, and SCOUT's Deep Umbra
shadow model (Accumulated Shadow) reads it.
The Widgets tab sets the height column, the zoom level and the maximum height.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_rasters.node_outputs import rasterize_buildings

return rasterize_buildings(
    input_0,
    attribute=[!! attribute !!],
    zoom=int([!! zoom !!]),
    max_height=float([!! max_height !!]),
    output_file=curio_output_file,
)
