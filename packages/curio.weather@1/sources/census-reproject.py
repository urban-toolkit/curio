"""Reproject census to EPSG:3395.

Input: UTCI Zonal Mean's polygons. Returns them in TARGET_CRS, those whose mean
UTCI is not above 0 left out, named `census` for the views.

Settings:
- SOURCE_CRS: the CRS the census polygons are in.
- TARGET_CRS: the CRS the views draw them in.
"""

from weather_census import reproject_census

SOURCE_CRS = 32632
TARGET_CRS = 3395

return reproject_census(input_0, source_crs=SOURCE_CRS, target_crs=TARGET_CRS)
