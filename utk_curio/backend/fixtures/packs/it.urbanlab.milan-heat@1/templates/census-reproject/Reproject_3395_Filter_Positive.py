"""Reproject the merged census table and tag it for downstream views.

The Milan census GeoJSON ships in UTM 32632; AUTK_MAP's tile pipeline
expects EPSG:3395, so we reset the CRS and reproject. Polygons that
ended up with a non-positive UTCI mean are dropped (they overlap nodata
pixels and would otherwise clip the colour scale).

The ``metadata`` assignment goes through ``__dict__`` rather than plain
attribute syntax: pandas emits a ``UserWarning`` when setting an
unknown attribute on a sliced DataFrame, and curio's sandbox treats any
non-empty stderr as a node failure during e2e. Curio reads ``.metadata``
back through ``getattr`` (parsers.py), so both write paths work — but
only the dict path stays warning-free.
"""

gdf = arg

filtered_gdf = gdf.set_crs(32632)
filtered_gdf = filtered_gdf.to_crs(3395)
filtered_gdf = filtered_gdf[filtered_gdf["mean"] > 0]

filtered_gdf.__dict__["metadata"] = {"name": "census"}

return filtered_gdf
