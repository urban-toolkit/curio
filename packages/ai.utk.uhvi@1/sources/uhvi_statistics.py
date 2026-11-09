"""UHVI's statistics over zones: the mean of a UHVI raster under each polygon of
a GeoDataFrame (``zonal_mean``), which UHVI Zonal Stats calls with its two
inputs.
"""

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask

#: What node code calls.
__all__ = ["zonal_mean"]


def zonal_mean(first, second):
    """The mean of a raster's first band under each polygon of a GeoDataFrame:
    a copy of the GeoDataFrame with the column ``uhvi_mean``, named
    ``uhvi_zonal``.

    *first* and *second* are the raster, an open ``rasterio`` dataset, and the
    polygons, a ``GeoDataFrame``, in either order: each is told apart by its
    type, so the node's two input circles take them either way round. One
    that is None, a circle with no edge, is left out, and anything but one
    raster and one GeoDataFrame is refused with the types that came. The
    polygons are reprojected to the raster's CRS, or given it when they have
    none. A cell whose center is in a polygon counts toward its mean, the
    raster's nodata cells never do, and a polygon over no cell with a value
    has a NaN mean.
    """
    raster, polygons = _raster_and_polygons([x for x in (first, second) if x is not None])

    values = raster.read(1).astype(float)
    nodata = raster.nodata
    if nodata is not None:
        values = np.where(values == nodata, np.nan, values)

    transform = raster.transform
    raster_crs = raster.crs

    if polygons.crs is None:
        polygons = polygons.set_crs(raster_crs)
    else:
        polygons = polygons.to_crs(raster_crs)

    means = []
    for geom in polygons.geometry:
        mask = geometry_mask(
            [geom],
            transform=transform,
            invert=True,
            out_shape=values.shape,
        )
        masked = np.where(mask, values, np.nan)
        mean = float(np.nanmean(masked))
        means.append(mean if np.isfinite(mean) else np.nan)

    polygons = polygons.copy()
    polygons["uhvi_mean"] = means
    polygons.metadata = {"name": "uhvi_zonal"}
    return polygons


def _raster_and_polygons(received):
    """``(raster, polygons)`` among *received*, told apart by type."""
    raster = next((x for x in received if isinstance(x, rasterio.io.DatasetReader)), None)
    polygons = next((x for x in received if isinstance(x, gpd.GeoDataFrame)), None)
    if raster is None or polygons is None:
        raise RuntimeError(
            "UHVI Zonal Stats expects a Raster + GeoDataFrame pair. "
            f"Got: {[type(x).__name__ for x in received]}"
        )
    return raster, polygons
