"""UTCI Zonal Mean.

Input, in order: the mean radiant temperature raster on input_0, which places
the grid; UTCI from raster + weather's `(grid, shape)` on input_1; the census
polygons on input_2, with their `gt_65`. Returns the polygons' geometry, `mean`,
the mean UTCI over each polygon, and `gt_65`.
"""

from weather_census import utci_zonal_mean

return utci_zonal_mean([!! input_0 !!], [!! input_1 !!], [!! input_2 !!])
