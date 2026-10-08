# SCOUT's flood function

`flood_simulation.py` is copied unchanged from SCOUT, https://github.com/urban-toolkit/scout,
commit b98369e5, file `backend/compute/quad_city_flooding_simulation/scripts/flood_simulation.py`
(blob a0ec9390, the same blob as `backend/models/flooding/scripts/flood_simulation.py`, the copy
SCOUT's example dataflows import).

`test_scout_flood.py` runs it, as SCOUT's flood example calls it, on the Data Catalog's copy of
SCOUT's rasters (`datasets/data.scout.quad-cities-flood@1`), and compares what it writes with what the
`scout.flood@1` package's Flood Projection node, SCOUT's function with its paths as arguments, gives.
