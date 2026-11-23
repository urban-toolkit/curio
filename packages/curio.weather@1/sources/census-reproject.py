"""Reproject census to EPSG:3395.

Input: UTCI Zonal Mean's polygons. Returns them in the target CRS, those whose
mean UTCI is not above 0 left out, named `census` for the views.

The Widgets tab sets the CRS the census polygons are in and the CRS the views
draw them in, each as its EPSG code.
"""

from weather_census import reproject_census

return reproject_census(
    input_0,
    source_crs=int([!! source_crs !!]),
    target_crs=int([!! target_crs !!]),
)
