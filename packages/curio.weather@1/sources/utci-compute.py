"""UTCI from raster + weather.

Input: the mean radiant temperature raster on input_0, as Milan MRT Loader
returns it, and the hourly weather table on input_1, as ERA5 Milan Weather
returns it. Returns `(grid, shape)`: the Universal Thermal Climate Index of
each cell, as a list of rows, and the grid's `[width, height]`, which UTCI
Zonal Mean takes with the raster.

Settings:
- TIMESTAMP: the hour, the weather table's `it`, whose weather is used.
- UPSCALE_FACTOR: the raster is read at this times its width and height.
"""

from weather_utci import utci_grid

TIMESTAMP = 12
UPSCALE_FACTOR = 1.0

return utci_grid(
    [!! input_0 !!], [!! input_1 !!],
    timestamp=TIMESTAMP, upscale_factor=UPSCALE_FACTOR,
)
