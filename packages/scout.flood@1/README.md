# `scout.flood@1`: SCOUT Flood

SCOUT's flood function, ported from [SCOUT](https://github.com/urban-toolkit/scout)
(`backend/compute/quad_city_flooding_simulation`). It reads a region of SCOUT's
flood projections for the Quad Cities and gives its flood depth with the
nature-based solutions (NbS) you choose in place.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.flood/flood-projection` | Flood Projection | None | `(depth, metrics)`: one RASTER and one table |

## Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Top-left corner (`topleft`) | 41.4669, -90.4836 | The region's north-west corner |
| Bottom-right corner (`bottomright`) | 41.441, -90.4577 | The region's south-east corner |
| Projection period (`year`) | `2020 - 2040` | One of `2020 - 2040`, `2050 - 2080` and `2080 - 2100` |
| Nature-based solutions (`use_NBS_classes`) | All six | The solutions in place |

Each solution stands for one or two codes of SCOUT's class raster:

| Solution | Codes |
|---|---|
| Bioswales/Infiltration trenches | 21 |
| Permeable pavements | 31 |
| Retention ponds | 43 |
| Infiltration trench | 52 |
| Bioswales | 71, 81 |
| Constructed wetlands | 90, 95 |

## Outputs

A cell takes the depth with NbS where its class is one of the chosen solutions,
and the depth without NbS elsewhere.

- **depth**: the region's flood depth in metres, one band, in EPSG:4326, on the
  rasters' own cells (about 8 by 11 m). A cell with no depth holds no value. An
  Autark map draws it as `input_0`:

  ```json
  {"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
  ```

- **metrics**: one row, `median flood depth` and `mean flood depth`, in metres,
  over the cells that hold a depth.

## Data

The node reads seven Data Catalog datasets: the NbS classes
(`data.scout.flood-nbs-classes`) and, for each period, the depth with NbS and
without (`data.scout.flood-depth-2020-2040-nbs`, `data.scout.flood-depth-2020-2040-no-nbs`,
and the same for `2050-2080` and `2080-2100`). Curio ships crops of SCOUT's
rasters that cover longitude -90.4869 to -90.4544 and latitude 41.4377 to
41.4702, so the corners must lie inside that area. The data is SCOUT's
(urban-toolkit/scout), used with the permission of SCOUT's authors.

## A dataflow

```
[ Parameter: timeline ]
[ Flood Projection: no NbS ] ──► [ Flood depth ] ─────────► [ Compare Scenarios: depth change ]
                            └──► [ Median and mean depth ] ► [ Compare Scenarios: median flood depth ]
[ Flood Projection: NbS ]    ──► (the same two nodes, into the same two)
```

The test dataflow [FloodScenarios](../../docs/examples/dataflows/FloodScenarios.json)
is this dataflow: two scenarios, No NbS and NbS, read the period from one
Parameter node. One Compare Scenarios node maps NbS minus No NbS, and the other
charts each scenario's median flood depth.

## Setup

Curio installs the package's one Python library with it, `rasterio`. The package
is installed for you when Curio starts with `--with-examples`, and its datasets
ship in the Data Catalog.
