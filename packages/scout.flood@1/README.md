# `scout.flood@1`: SCOUT Flood

SCOUT's Quad Cities flood projection, ported from
[SCOUT](https://github.com/urban-toolkit/scout)
(`backend/models/flooding`). For a region and a projection period, each cell
takes the projected flood depth with nature-based solutions (NbS) where its
class is one of the chosen solutions, and the depth without NbS elsewhere.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.flood/flood-projection` | Flood Projection | none | `(depth, metrics)`: one RASTER, the flood depth in metres, and SCOUT's metrics, a table of one row |

## Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Top-left corner (`topleft`) | 41.6242105, -90.6879323 | The region's north-west corner, SCOUT's example's |
| Bottom-right corner (`bottomright`) | 41.4150156, -90.4252158 | The region's south-east corner, SCOUT's example's |
| Projection period (`timeline`) | `2020 - 2040` | `2020 - 2040`, `2050 - 2080` or `2080 - 2100` |
| Nature-based solutions (`use_NBS_classes`) | all six | The solutions in place: bioswales/infiltration trenches, permeable pavements, retention ponds, infiltration trench, bioswales, constructed wetlands |

The corners' defaults cover SCOUT's whole grid, 2592 by 2064 cells, as SCOUT's
flood example does. Two Flood Projection nodes in one dataflow, as in two
scenarios, share the region and the period by reading them from Parameter nodes (`[!! @timeline !!]` in place of
`[!! timeline !!]`).

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

The node hands SCOUT's function the corners as SCOUT's `"lon, lat"` text, the
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

A node after it takes one part. The depth, for a map or Compare Scenarios'
difference:

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
          └──► [ Metrics ] ──► [ Compare Scenarios: chart ]
```

The test dataflow [FloodScenarios](../../docs/examples/dataflows/FloodScenarios.json)
compares SCOUT's two flood scenarios: no nature-based solution in place, and
all six. A shared period and region, a map of each scenario's depth, a map of how much
the depth changes, and a pie chart of each scenario's median flood depth,
SCOUT's flood example's metric, each value drawn as it is.

## Setup

Curio installs the package's Python libraries with it: `rasterio`, `numpy`,
`pandas`, `geopandas` and `shapely` (SCOUT's function imports the last two).
It is installed for you when Curio starts with `--with-examples`.
