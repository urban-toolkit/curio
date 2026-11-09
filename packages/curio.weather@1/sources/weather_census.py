"""Weather's steps over the census polygons: the mean UTCI of each polygon
(``utci_zonal_mean``), which UTCI Zonal Mean calls, the polygons reprojected
for the views (``reproject_census``), which Reproject census to EPSG:3395
calls, and their ``gt_65`` column alone (``gt65_column``), which Project gt_65
column calls.
"""

import numpy as np
from rasterstats import zonal_stats

#: What node code calls.
__all__ = ["utci_zonal_mean", "reproject_census", "gt65_column"]


def utci_zonal_mean(raster, utci, census):
    """The mean UTCI of each census polygon: the polygons' geometry, ``mean``
    and ``gt_65``.

    *raster* is the raster the index was computed from, an open ``rasterio``
    dataset, whose transform, scaled to the grid's shape, places the grid.
    *utci* is UTCI from raster + weather's ``(grid, shape)``, the grid as a
    list of rows and its shape as ``[width, height]``. *census* is a
    GeoDataFrame of polygons in the raster's CRS with a ``gt_65`` column; it
    gains the ``mean`` column too. A NaN cell counts toward no mean, and a
    polygon over no cell with a value has none. ``rasterstats`` takes the NaN
    cells as an explicit nodata value, so it warns about none of them.
    """
    utci_list = utci[0]
    utci_shape = utci[1]

    grid = np.asarray(utci_list, dtype=float)
    if grid.ndim != 2:
        raise ValueError(
            f"Expected 2D UTCI array, got shape={grid.shape}, ndim={grid.ndim}"
        )

    transform = raster.transform * raster.transform.scale(
        (raster.width / utci_shape[0]),
        (raster.height / utci_shape[1]),
    )

    nodata_value = -999.0
    grid_for_stats = np.where(np.isnan(grid), nodata_value, grid)

    joined = zonal_stats(
        census,
        grid_for_stats,
        stats=["min", "max", "mean", "median"],
        affine=transform,
        nodata=nodata_value,
    )

    census["mean"] = [d["mean"] for d in joined]
    return census.loc[:, [census.geometry.name, "mean", "gt_65"]]


def reproject_census(census, *, source_crs=32632, target_crs=3395):
    """The census polygons in *target_crs*, those whose mean UTCI is not
    above 0 left out, named ``census`` for the views that read it.

    *census* is UTCI Zonal Mean's output, in *source_crs*: the Milan census
    is in UTM zone 32N, EPSG:32632. That CRS is set on the table, which
    refuses a table in another, then the polygons are reprojected to
    *target_crs*, the World Mercator of EPSG:3395 by default. A polygon whose
    ``mean`` is 0, below 0 or missing lies over nodata cells and would
    stretch the map's color scale. The name is the table's ``metadata``,
    which Curio reads to name it, set through ``__dict__`` so that pandas
    does not warn of an attribute set on a slice of a table.
    """
    filtered = census.set_crs(source_crs)
    filtered = filtered.to_crs(target_crs)
    filtered = filtered[filtered["mean"] > 0]

    filtered.__dict__["metadata"] = {"name": "census"}

    return filtered


def gt65_column(census):
    """The census table cut to its ``gt_65`` column, the residents over 65 of
    each polygon, for a chart of them alone.

    *census* is any table with a ``gt_65`` column, such as Reproject census
    to EPSG:3395's output. The result is a table, its geometry left out, with
    the same index.
    """
    return census.loc[:, ["gt_65"]]
