"""Weather's thermal comfort: the Universal Thermal Climate Index of each cell of
a mean radiant temperature raster, under one hour's weather (``utci_grid``),
which UTCI from raster + weather calls.

Its mean over census polygons is ``weather_census``'s. Only this module
imports ``pythermalcomfort``, whose code numba compiles as it loads, so only
the node that computes the index loads it.
"""

import numpy as np
from pythermalcomfort import models
from rasterio.warp import Resampling

#: What node code calls.
__all__ = ["utci_grid"]


def utci_grid(raster, weather, *, timestamp=12, upscale_factor=1.0):
    """The Universal Thermal Climate Index of each cell of a mean radiant
    temperature raster, under one hour's weather: ``(grid, shape)``, the grid
    as a list of its rows and its shape as ``[width, height]``.

    *raster* is an open ``rasterio`` dataset of mean radiant temperature in
    °C, read at *upscale_factor* times its width and height; its nodata
    cells are NaN in the grid. *weather* is a table with a row per hour, the
    hour in ``it``: the row whose ``it`` is *timestamp* gives the air
    temperature ``Td`` (°C), the wind speed ``Wind`` (m/s) and the relative
    humidity ``RH`` (%). The index is ``pythermalcomfort``'s, in SI units,
    with ``limit_inputs=False``: a cell whose radiant temperature is more than
    30 °C above the air's, common at noon in Milan, keeps its index, which the
    library's default would make NaN. The grid is lists, not an array, so it
    reaches the next node as it is, and UTCI Zonal Mean places it on the
    raster by its shape.
    """
    data = raster.read(
        out_shape=(
            raster.count,
            int(raster.height * upscale_factor),
            int(raster.width * upscale_factor),
        ),
        resampling=Resampling.nearest,
        masked=True,
    )
    # A masked read, filled: NaN wherever the raster has no value, whatever
    # its nodata value is.
    data = data.astype(float).filled(np.nan)

    hour = weather[weather["it"] == timestamp]
    tdb = float(hour["Td"].values[0])
    v = float(hour["Wind"].values[0])
    rh = float(hour["RH"].values[0])

    utci = models.utci(
        tdb=tdb, tr=data[0], v=v, rh=rh, units="SI", limit_inputs=False,
    )
    grid = np.asarray(getattr(utci, "utci", utci), dtype=float)

    if grid.ndim == 3 and grid.shape[0] == 1:
        grid = grid[0]
    if grid.ndim != 2:
        raise ValueError(
            f"UTCI must be 2D, got shape={grid.shape}, ndim={grid.ndim}"
        )

    return (grid.tolist(), [grid.shape[1], grid.shape[0]])
