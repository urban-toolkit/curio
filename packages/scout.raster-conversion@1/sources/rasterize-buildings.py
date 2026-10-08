"""Rasterize Buildings: SCOUT's building rasterizer, "OSM vector to raster".

Input: a buildings layer, a GeoDataFrame of polygons with a CRS and a column
of heights in metres.
Output: the 256 by 256 tiles SCOUT writes, 8-bit gray where 255 is the maximum
height, in EPSG:3395, saved as one of this dataflow's computed datasets, under
the name the "Save tiles as" widget gives ("tiles"); and a table of them, one
row per tile: zoom, x, y and the maximum height. Mosaic Tiles, given the same
name, puts the tiles together into one raster.
The Widgets tab sets the height column, the zoom level, the maximum height and
the name.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_raster_conversion.convert_to_raster import convert_raster
from scout_raster_conversion.mosaic import tile_table

tiles = curio_save_folder([!! tiles !!])
convert_raster(input_0, [!! attribute !!], int([!! zoom !!]), tiles, max_height=float([!! max_height !!]))
return tile_table(tiles, int([!! zoom !!]), float([!! max_height !!]))
