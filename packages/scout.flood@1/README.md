# `scout.flood@1`: SCOUT Flood

SCOUT's Quad Cities flood projection, ported from
[SCOUT](https://github.com/urban-toolkit/scout)
(`backend/models/flooding`). For a projection period, each cell of SCOUT's whole grid
takes the projected flood depth with nature-based solutions (NbS) where its
class is one of the chosen solutions, and the depth without NbS elsewhere.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.flood/flood-projection` | Flood Projection | none; optionally a RASTER of NbS classes on SCOUT's grid, which code that reads `input_0` can use in place of SCOUT's `nbs_classes.tif` (the FloodRisk example merges classes this way) | `(depth, metrics)`: one RASTER, the flood depth in metres, and SCOUT's metrics, a table of one row |

## Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Projection period (`timeline`) | `2020 - 2050` | `2020 - 2050`, `2050 - 2080` or `2080 - 2100` |
| Nature-based solutions (`use_NBS_classes`) | all four | The solutions in place, one per kind: bioswales/infiltration trenches (SCOUT's classes 21, 52, 71 and 81), permeable pavements, retention ponds, constructed wetlands |

The region is SCOUT's whole grid, 2592 by 2064 cells, as SCOUT's flood example
runs it: its corners are fixed in the node's code. Two Flood Projection nodes in
one dataflow, as in two scenarios, share the period by reading it from a
Parameter node (`[!! @timeline !!]` in place of `[!! timeline !!]`).

## SCOUT's code

`sources/scout_flood/flood_simulation.py` is SCOUT's
`backend/models/flooding/scripts/flood_simulation.py` (commit `b98369e5`) as
SCOUT wrote it, with these changes, each marked `# Curio:`:

- `data_dir`, the folder SCOUT's rasters are read from, in place of
  `./models/flooding/data_substitutes`, and the rasters' names in the bundle
  (`nbs_classes.tif`, `<period>_NbS.tif`, `<period>_noNbS.tif`) in place of
  SCOUT's (`NBS_others_5m_4326_cropped_cleaned_resampled.tif`,
  `<period>_NbS_4326_cropped.tif`, `<period>_noNbS_4326_cropped.tif`);
- `output_path`, where the raster is written, in place of
  `./data/served/raster/<output>.tif` (its default);
- the metrics are returned as a table, `return df`, and SCOUT's lines that
  write them to `./data/served/metric/<output>.csv` are left out.

On every cell, and in its metrics, the
port gives what SCOUT's function gives on SCOUT's own files
(`utk_curio/backend/tests/test_packages/test_scout_flood.py`).

The node hands SCOUT's function the grid's corners as SCOUT's `"lon, lat"` text, the
dataset's `data` folder as `data_dir`, a file `curio_output_file` gives
for the raster, and returns the raster and the metrics SCOUT's function
returns. No CSV is written.

## The data

SCOUT's seven rasters are the Data Catalog's `data.scout.quad-cities-flood@1`,
a bundle of seven GeoTIFFs beside its `bundle.json`: `nbs_classes.tif`, the
NbS class raster, and for each period `<period>_NbS.tif` and
`<period>_noNbS.tif`, the depth with and without NbS. Every cell is SCOUT's, compressed
losslessly; [`scripts/build_scout_flood_datasets.py`](../../scripts/build_scout_flood_datasets.py)
builds it from SCOUT's `data_substitutes` folder.

## Output

`(depth, metrics)`:

- **depth**: one GeoTIFF in EPSG:4326 on SCOUT's grid, one band of metres,
  written by SCOUT's code: a cell with no depth holds no value.
- **metrics**: SCOUT's metrics as a table of one row, `median flood depth`
  and `mean flood depth`, the numbers SCOUT computes (and SCOUT writes to its
  CSV).

A node after it takes one part. The depth, for a map or a raster difference
(`curio_raster_calculate` in a Python node):

```python
return input_0[0]
```

and the metrics, for a chart:

```python
return input_0[1]
```

An Autark map draws the depth as `input_0`:

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1", "colorMapInterpolator": "interpolateBlues"}]}}
```

## A dataflow

```
[ Flood Projection ] ──► [ Depth ] ──► [ Autark: map of the depth ]
          │
          └──► [ Metrics ] ──► [ Vega-Lite: scenarios compared ]
```

The test dataflow [FloodScenarios](../../docs/examples/dataflows/FloodScenarios.json)
compares SCOUT's two flood scenarios: no nature-based solution in place, and
all four. A shared period, a map of each scenario's depth, a Raster
Calculator's absolute change in depth on a map, and a Vega-Lite table of each
scenario's median and mean flood depth, SCOUT's flood example's metrics.

## Setup

Curio installs the package's Python libraries with it: `rasterio`, `numpy`,
`pandas`, `geopandas` and `shapely` (SCOUT's function imports the last two).
It is installed for you when Curio starts with `--with-examples`.
