import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import geometry_mask

# Curio raster contract: the upstream raster port delivers a
# `rasterio.io.DatasetReader`, not a dict of arrays. Read the band lazily
# here so the upstream loader stays cheap.
#
# The raster and the polygons arrive on the node's two input circles,
# input_0 and input_1 (a circle with no edge is None). Sort them by Python
# type rather than by circle so the downstream contract is stable regardless
# of how the user dragged the edges.
def _sort_inputs(received):
    items = list(received) if isinstance(received, (list, tuple)) else [received]
    raster = next((x for x in items if isinstance(x, rasterio.io.DatasetReader)), None)
    polygons = next((x for x in items if isinstance(x, gpd.GeoDataFrame)), None)
    if raster is None or polygons is None:
        raise RuntimeError(
            "UHVI Zonal Stats expects a Raster + GeoDataFrame pair. "
            f"Got: {[type(x).__name__ for x in items]}"
        )
    return raster, polygons

src, gdf = _sort_inputs([x for x in (input_0, input_1) if x is not None])

values = src.read(1).astype(float)
nodata = src.nodata
if nodata is not None:
    values = np.where(values == nodata, np.nan, values)

transform = src.transform
raster_crs = src.crs

if gdf.crs is None:
    gdf = gdf.set_crs(raster_crs)
else:
    gdf = gdf.to_crs(raster_crs)

means = []
for geom in gdf.geometry:
    mask = geometry_mask(
        [geom],
        transform=transform,
        invert=True,
        out_shape=values.shape,
    )
    masked = np.where(mask, values, np.nan)
    mean = float(np.nanmean(masked))
    means.append(mean if np.isfinite(mean) else np.nan)

gdf = gdf.copy()
gdf["uhvi_mean"] = means
gdf.metadata = {"name": "uhvi_zonal"}

return gdf
