"""Mosaic Rasters.

Input: a raster collection's rows, as Data Loading's `curio_load_collection(...)`
returns them, usually filtered first to one year, one sensor or one area.
Output: one raster, a virtual mosaic (a GDAL VRT) of every tile, which any
node that takes a RASTER reads, the zonal-statistics nodes included. The
tiles stay where they are: the mosaic points at them.

Every tile must share its CRS, resolution, band count, data type and no-data
value, and be north-up. The node names the first difference it finds. Where
tiles overlap, a tile's no-data pixels leave the tile below them showing.
"""
# Curio's raster helpers lay rasters on one grid side by side.
from utk_curio.sandbox.util.rasters import mosaic_collection

return mosaic_collection(input_0, curio_output_file)
