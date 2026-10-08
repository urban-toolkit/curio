"""Flood Projection: SCOUT's Quad Cities flood projection, simulate_flood_projection.

Input: none. SCOUT's rasters are the Data Catalog's data.scout.quad-cities-flood.
Output: (depth, metrics).
- depth: the flood depth in metres, one raster in EPSG:4326 on SCOUT's grid: a
  cell takes the depth with nature-based solutions (NbS) where its class is
  one of the chosen solutions, and the depth without NbS elsewhere. An Autark
  map draws it as input_0, band band_1.
- metrics: SCOUT's metrics, the median and mean flood depth, one row (SCOUT
  writes them as a CSV; here its function returns them).
A node after it takes either part, input_0[0] or input_0[1].
The Widgets tab sets the region's corners, the projection period and the
solutions. Two scenarios that share the region and the period
read them from Parameter nodes instead, by putting @topleft, @bottomright and
@timeline in the code's references to those widgets.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
import hashlib
import json
import os

import rasterio
from scout_flood.flood_simulation import simulate_flood_projection

topleft, bottomright = [!! topleft !!], [!! bottomright !!]
period, chosen = [!! timeline !!], [!! use_NBS_classes !!]
# SCOUT's rasters, beside the bundle's bundle.json.
rasters = os.path.dirname(curio_data_path("data.scout.quad-cities-flood"))
# The raster SCOUT's code writes is the node's output. Its name, one per run's
# settings, keeps two scenarios from writing the same file.
settings = json.dumps([topleft, bottomright, period, sorted(chosen)], sort_keys=True)
depth = curio_output_file(f"flood-{hashlib.sha256(settings.encode()).hexdigest()[:16]}.tif")
metrics = simulate_flood_projection(
    f"{topleft['lon']!r}, {topleft['lat']!r}",
    f"{bottomright['lon']!r}, {bottomright['lat']!r}",
    "flood",
    year=period,
    use_NBS_classes=chosen,
    data_dir=rasters,
    output_path=depth,
)
return rasterio.open(depth), metrics
