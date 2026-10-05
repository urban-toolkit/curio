"""Rasterize Buildings: SCOUT's building rasterizer, "OSM vector to raster".

Input: a buildings layer, a GeoDataFrame of polygons with a CRS and a column
of heights in metres.
Output: (mosaic, tiles).
- mosaic: one raster in EPSG:3395, each cell a height in metres. An Autark map
  draws it as input_0, band band_1.
- tiles: one row per map tile, with zoom, x, y and png, the 8-bit grayscale
  PNG (base64) SCOUT's Deep Umbra shadow model reads, where 255 is the
  maximum height.
The Widgets tab sets the height column, the zoom level and the maximum height.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_raster_conversion.node_outputs import rasterize_buildings

return rasterize_buildings(
    arg,
    attribute=[!! attribute !!],
    zoom=int([!! zoom !!]),
    max_height=float([!! max_height !!]),
    output_file=curio_output_file,
)
