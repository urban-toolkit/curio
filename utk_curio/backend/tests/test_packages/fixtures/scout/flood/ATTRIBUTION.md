# SCOUT's flood projections, recorded

These files were recorded by
[`scripts/generate_scout_flood_fixture.py`](../../../../../../../scripts/generate_scout_flood_fixture.py)
from SCOUT, https://github.com/urban-toolkit/scout, folder
`backend/models/flooding/`: SCOUT's flood simulation and the rasters of its
"Planning nature-based flood mitigation" use case.

- `block/data/`: a block of 200 by 200 cells of Curio's dataset
  `data.scout.quad-cities-flood`, laid out as the dataset is: its seven files
  (SCOUT's rasters, the depths as float32) and its `bundle.json`. The block is
  cells 450 to 649 across and 1500 to 1699 down: the one, on a 50-cell step,
  with the most cells that hold both a depth and an NbS class.
- `scout_<case>.tif` and `scout_<case>.csv`: what SCOUT's own
  `simulate_flood_projection` (`scripts/flood_simulation.py`, imported
  unchanged) wrote for the same block of SCOUT's float64 files, its corners
  the block's edges: the combined flood raster and its median and mean flood
  depth. The cases:
  - `2020_2040_all`: 2020-2040, every nature-based solution;
  - `2020_2040_none`: 2020-2040, none;
  - `2050_2080_none`: 2050-2080, none, the period whose no-NbS raster marks no
    depth with -1.8e308 rather than NaN.
- `block.json`: the block's window and bounds, the corners SCOUT was called
  with, and each case's period and solutions.

The `scout.flood-simulation@1` tests read `block/data/` as the dataset, with
`curio_load_data(..., part=...)`, run the package's port on it and compare
it with SCOUT's rasters and metrics.
