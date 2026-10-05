# `scout.flood-simulation@1`: SCOUT Flood Simulation

SCOUT's flood simulation, ported from
[SCOUT](https://github.com/urban-toolkit/scout) (`backend/models/flooding`), the
model behind its "Planning nature-based flood mitigation" use case. For a period
and an area of the Quad Cities, it projects the flood depth of each cell with
nature-based solutions (NbS) where the cell's class is one of the solutions
chosen, and without them elsewhere.

The data is not in this package. It is `data.scout.quad-cities-flood` in the
[Data Catalog](../../docs/DATA-CATALOG.md): one dataset of seven GeoTIFFs on one
grid, named as SCOUT names them. `NBS_others_5m.tif` holds the NbS class of
each cell, and `<period>_NbS.tif` and `<period>_noNbS.tif` the depth with NbS
and without, for `2020_2040`, `2050_2080` and `2080_2100`.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.flood-simulation/simulate-flood` | Simulate Flood | `(classes, nbs, no_nbs)`: three rasters on one grid | One RASTER: flood depth in metres |

The input comes from a Data Loading node, which reads the three files of a
period over an area by name:

```python
box = (west, south, east, north)
classes = curio_load_data("data.scout.quad-cities-flood", part="NBS_others_5m.tif", bounds=box)
nbs = curio_load_data("data.scout.quad-cities-flood", part="2020_2040_NbS.tif", bounds=box)
no_nbs = curio_load_data("data.scout.quad-cities-flood", part="2020_2040_noNbS.tif", bounds=box)
return classes, nbs, no_nbs
```

The node checks that the three share one grid, as SCOUT does before combining
them.

## Settings

The node's **Widgets** tab holds its setting:

| Widget | Default | What it sets |
|---|---|---|
| Nature-based solutions (`nbs`) | all six | The solutions in place, as SCOUT names them |

The solutions and the classes they cover are SCOUT's:

| Solution | Classes |
|---|---|
| Bioswales/Infiltration trenches | 21 |
| Permeable pavements | 31 |
| Retention ponds | 43 |
| Infiltration trench | 52 |
| Bioswales | 71, 81 |
| Constructed wetlands | 90, 95 |

With none chosen, every cell takes the depth without NbS: SCOUT's baseline.

## Output

One raster on the inputs' grid (EPSG:4326, about 11 m cells): one float32
band, the projected depth in metres, NaN where the projection gives no depth.
Its tags hold the solutions used and SCOUT's metrics, the
`median_flood_depth` and `mean_flood_depth` over the cells with a depth. An
Autark map draws it as `input_0`:

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
```

**Raster Statistics** reads it for the same median and mean as a table, and
**Compare Scenarios** subtracts one projection from another.

## A dataflow

```
[ Data Loading: 3 rasters ]   ─┬─► [ Simulate Flood: with NbS ] ──► [ Autark: depth ]
                               └─► [ Simulate Flood: no NbS ]   ──► [ Autark: depth ]
```

[Example 25](../../docs/examples/25-scout-flooding.md) is this dataflow, with
the two projections as scenarios, their difference on a map and their median
depths compared.

## Setup

Curio installs the package's Python library with it, `rasterio`. It is
installed for you when Curio starts with `--with-examples`.
