"""Flood Projection: SCOUT's flood function for the Quad Cities.

Reads the region's window of SCOUT's nature-based solutions (NbS) class raster
and of the period's flood depth rasters, with and without NbS. A cell takes the
depth with NbS where its class is one of the chosen solutions, and the depth
without NbS elsewhere.
Output: (depth, metrics).
- depth: the region's flood depth in metres, a raster in EPSG:4326. An Autark
  map draws it as input_0, band band_1.
- metrics: one row, the median flood depth and the mean flood depth.
The Widgets tab sets the region's corners, the period and the solutions.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_flood.flood_simulation import simulate_flood_projection

# The Data Catalog's crops of SCOUT's rasters: the NbS classes, and each
# period's depth with NbS and without.
rasters = {
    "classes": curio_data_path("data.scout.flood-nbs-classes"),
    "2020 - 2040": (
        curio_data_path("data.scout.flood-depth-2020-2040-nbs"),
        curio_data_path("data.scout.flood-depth-2020-2040-no-nbs"),
    ),
    "2050 - 2080": (
        curio_data_path("data.scout.flood-depth-2050-2080-nbs"),
        curio_data_path("data.scout.flood-depth-2050-2080-no-nbs"),
    ),
    "2080 - 2100": (
        curio_data_path("data.scout.flood-depth-2080-2100-nbs"),
        curio_data_path("data.scout.flood-depth-2080-2100-no-nbs"),
    ),
}

return simulate_flood_projection(
    [!! topleft !!],
    [!! bottomright !!],
    curio_output_file,
    year=[!! year !!],
    use_NBS_classes=[!! use_NBS_classes !!],
    rasters=rasters,
)
