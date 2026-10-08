"""Mosaic Tiles: the tiles Rasterize Buildings saved, side by side in one raster.

Input: Rasterize Buildings' table of tiles, whose zoom and maximum height say
how to put them together. The tiles are the computed dataset of this dataflow
that the "Tiles" widget names ("tiles"), the name Rasterize Buildings saved
them under.
Output: one raster in EPSG:3395, each cell a height in metres (a tile's gray
level times the maximum height over 255). A tile with no building near it is
0, the ground. An Autark map draws it as input_0, band band_1; SCOUT's Deep
Umbra shadow model (Accumulated Shadow) reads it.
"""
from scout_raster_conversion.mosaic import mosaic

return mosaic(
    curio_computed_path([!! tiles !!]),
    int(input_0["zoom"].iloc[0]),
    float(input_0["max_height"].iloc[0]),
    curio_output_file,
)
