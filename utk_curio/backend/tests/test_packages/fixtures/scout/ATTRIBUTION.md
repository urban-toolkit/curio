# SCOUT's committed results

These files are copied unchanged from SCOUT, https://github.com/urban-toolkit/scout,
commit b98369e5, folder `backend/data/dataflows/aedc4c6b73934b14979101108ee51f42_computed/`:
the outputs SCOUT committed for its high-rise shadow example.

- `A_buildings.geojson`: the buildings of the example's scenario A, 123 polygons in
  EPSG:4326 with a `height` column in metres.
- `A_rasters/`: the four zoom-16 height tiles SCOUT's `convert_raster` wrote for
  them, 8-bit gray, named `<zoom>_<x>_<y>.png`.
- `A_shadows/`: the shadows SCOUT's Deep Umbra (`run_shadow_model`) drew for
  those tiles in summer, the season the example set: 8-bit gray, 255 is shadow
  all day, named as the tiles are.
- `A_shadows_metric.csv`: the metrics `run_shadow_model` wrote with them, the
  mean and median minutes of shadow on the ground.

The `scout.raster-conversion@1` tests rasterize `A_buildings.geojson` with the
package's port of `convert_raster` and compare the result with `A_rasters/`.

The `scout.shadow-simulation@1` tests run its Simulate Shadows node, with the
Model Catalog's `model.scout.deep-umbra`, on those tiles and compare the result
with `A_shadows/` and `A_shadows_metric.csv`.
