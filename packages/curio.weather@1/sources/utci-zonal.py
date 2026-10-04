"""Spatially join UTCI pixels into census polygons.

Its input circles, in order:

* input 0: rasterio dataset (carries the CRS / transform).
* input 1: ``(utci_list, utci_shape)`` from the ``utci-compute`` step.
* input 2: census polygon GeoDataFrame.

We rebuild the UTCI grid from the list-of-lists + shape, scale the
raster transform to match the (downsampled) grid, replace NaNs with an
explicit nodata sentinel so ``rasterstats`` does not emit a warning
(the sandbox treats non-empty stderr as a node failure during e2e),
and attach the per-polygon mean back to the GeoDataFrame.
"""

import numpy as np
from rasterstats import zonal_stats

dataset = [!! input 0 !!]
utci_list = [!! input 1 !!][0]
utci_shape = [!! input 1 !!][1]
gdf = [!! input 2 !!]

utci = np.asarray(utci_list, dtype=float)
if utci.ndim != 2:
    raise ValueError(
        f"Expected 2D UTCI array, got shape={utci.shape}, ndim={utci.ndim}"
    )

transform = dataset.transform * dataset.transform.scale(
    (dataset.width / utci_shape[0]),
    (dataset.height / utci_shape[1]),
)

nodata_value = -999.0
utci_for_stats = np.where(np.isnan(utci), nodata_value, utci)

joined = zonal_stats(
    gdf,
    utci_for_stats,
    stats=["min", "max", "mean", "median"],
    affine=transform,
    nodata=nodata_value,
)

gdf["mean"] = [d["mean"] for d in joined]
return gdf.loc[:, [gdf.geometry.name, "mean", "gt_65"]]
