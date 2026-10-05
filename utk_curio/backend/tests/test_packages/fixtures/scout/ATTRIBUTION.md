# SCOUT's committed results

These files are copied unchanged from SCOUT, https://github.com/urban-toolkit/scout,
commit b98369e5, folder `backend/data/dataflows/aedc4c6b73934b14979101108ee51f42_computed/`:
the outputs SCOUT committed for its high-rise shadow example.

- `A_buildings.geojson`: the buildings of the example's scenario A, 123 polygons in
  EPSG:4326 with a `height` column in metres.
- `A_rasters/`: the four zoom-16 height tiles SCOUT's `convert_raster` wrote for
  them, 8-bit gray, named `<zoom>_<x>_<y>.png`.

The `scout.raster-conversion@1` tests rasterize `A_buildings.geojson` with the
package's port of `convert_raster` and compare the result with `A_rasters/`.
