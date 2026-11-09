"""UHVI Zonal Stats.

Input: a UHVI raster, as UHVI Loader returns it, and polygons, as UHVI Zones
returns them, on the node's two input circles in either order. Returns the
polygons with `uhvi_mean`, the raster's mean under each.
"""

from uhvi_statistics import zonal_mean

return zonal_mean(input_0, input_1)
