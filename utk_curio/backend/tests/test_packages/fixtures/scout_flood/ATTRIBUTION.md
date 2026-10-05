# SCOUT's flood function

`flood_simulation.py` is copied unchanged from SCOUT, https://github.com/urban-toolkit/scout,
commit b98369e5, file `backend/compute/quad_city_flooding_simulation/scripts/flood_simulation.py`
(blob a0ec9390, the same blob as `backend/models/flooding/scripts/flood_simulation.py`, the copy
SCOUT's example dataflows import).

The `scout.flood@1` tests run it, as SCOUT's flood example calls it, on the Data Catalog's crops
of SCOUT's rasters (`datasets/data.scout.flood-*`), and compare what it writes with what the
package's port returns.
