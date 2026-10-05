# SCOUT's committed results

These files are copied unchanged from SCOUT, https://github.com/urban-toolkit/scout,
commit b98369e5, folder `backend/data/dataflows/aedc4c6b73934b14979101108ee51f42_computed/`:
the outputs SCOUT committed for its high-rise shadow example.

- `A_buildings.geojson`: the buildings of the example's scenario A, 123 polygons in
  EPSG:4326 with a `height` column in metres.
- `A_rasters/`: the four zoom-16 height tiles SCOUT's `convert_raster` wrote for
  them, 8-bit gray, named `<zoom>_<x>_<y>.png`.
- `B_rasters/`: the same four tiles for scenario B, the buildings of A without 15
  of them.
- `A_shadows/`, `B_shadows/`: the accumulated shadow tiles SCOUT's
  `run_shadow_model` wrote from each scenario's rasters in summer, 8-bit gray.
- `A_shadows_metric.csv`, `B_shadows_metric.csv`: the mean and median accumulated
  shadow, in minutes, that it wrote with them.

The `scout.raster-conversion@1` tests rasterize `A_buildings.geojson` with the
package's port of `convert_raster` and compare the result with `A_rasters/`. The
`scout.shadow@1` tests run the package's port of `run_shadow_model` on `A_rasters/`
and `B_rasters/` and compare the results with the shadow tiles and the CSVs.
