"""Rasterize Buildings: SCOUT's building rasterizer, "OSM vector to raster".

Input: a buildings layer, a GeoDataFrame of polygons with a CRS and a column
of heights in metres.
Output: one raster in EPSG:3395, each cell a height in metres: the 256 by 256
tiles SCOUT writes, side by side. An Autark map draws it as input_0, band
band_1; SCOUT's Deep Umbra shadow model (Accumulated Shadow) reads it.
The Widgets tab sets the height column, the zoom level and the maximum height.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
import os
import tempfile

from scout_raster_conversion.convert_to_raster import convert_raster
from scout_raster_conversion.mosaic import mosaic

with tempfile.TemporaryDirectory() as work:
    buildings = os.path.join(work, "buildings")
    arg.to_file(buildings, driver="GeoJSON")
    rasters = os.path.join(work, "rasters")
    convert_raster(buildings, [!! attribute !!], int([!! zoom !!]), rasters, max_height=float([!! max_height !!]))
    return mosaic(rasters, int([!! zoom !!]), float([!! max_height !!]), curio_output_file)
