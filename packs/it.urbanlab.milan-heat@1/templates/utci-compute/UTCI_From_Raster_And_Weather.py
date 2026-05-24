"""Compute the Universal Thermal Climate Index per raster pixel.

`arg` arrives from a MERGE_FLOW: `arg[0]` is the rasterio dataset
(opened upstream by `mrt-load`), `arg[1]` is the meteorological
DataFrame (loaded by `weather-load`). The output is a `(grid, shape)`
tuple — Curio serialises numpy arrays poorly across the sandbox
boundary, so we return Python lists + an explicit `[width, height]`
shape that `utci-zonal` rebuilds on the other side.

Two non-obvious details preserved from
``docs/examples/09-heterogeneous-data-linked-views.md``:

* ``data.filled(np.nan)`` collapses the rasterio MaskedArray to a plain
  float array with NaN nodata regardless of the raster's sentinel.
* ``limit_inputs=False`` keeps UTCI valid where ``tr - tdb > 30``,
  which is common at noon in Milan (MRT ~60-70 °C, air ~30 °C). The
  default ``limit_inputs=True`` silently NaNs those pixels and the
  downstream map renders half-empty.
"""

import numpy as np
from pythermalcomfort import models
from rasterio.warp import Resampling

src = arg[0]
sensor = arg[1]
timestamp = 12

upscale_factor = 1.0
data = src.read(
    out_shape=(
        src.count,
        int(src.height * upscale_factor),
        int(src.width * upscale_factor),
    ),
    resampling=Resampling.nearest,
    masked=True,
)
data = data.astype(float).filled(np.nan)

sensor_filtered = sensor[sensor["it"] == timestamp]
tdb = float(sensor_filtered["Td"].values[0])
v = float(sensor_filtered["Wind"].values[0])
rh = float(sensor_filtered["RH"].values[0])

utci_result = models.utci(
    tdb=tdb, tr=data[0], v=v, rh=rh, units="SI", limit_inputs=False,
)
utci_grid = np.asarray(getattr(utci_result, "utci", utci_result), dtype=float)

if utci_grid.ndim == 3 and utci_grid.shape[0] == 1:
    utci_grid = utci_grid[0]
if utci_grid.ndim != 2:
    raise ValueError(
        f"UTCI must be 2D, got shape={utci_grid.shape}, ndim={utci_grid.ndim}"
    )

utci_list = utci_grid.tolist()
utci_shape = [utci_grid.shape[1], utci_grid.shape[0]]

return (utci_list, utci_shape)
