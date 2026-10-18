# `scout.rasters@1`: SCOUT Rasters

SCOUT's raster nodes. The **Raster Calculator** runs one operation over
rasters on one grid, cell by cell or a raster's statistics. **Rasterize
Buildings** is SCOUT's building rasterizer ("OSM vector to raster"), ported from
[SCOUT](https://github.com/urban-toolkit/scout) (`backend/compute/raster_conversion`):
it draws each building's height into map tiles and joins the tiles into one
raster, which an Autark map draws and SCOUT's Deep Umbra shadow model reads.

In the canvas palette, both nodes are in the **SCOUT Rasters** group of the
Packages dropdown.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.rasters/raster-calculator` | Raster Calculator | One to three RASTERs on one grid, one per input circle | One RASTER, or a DATAFRAME of one row of statistics |
| `scout.rasters/rasterize-buildings` | Rasterize Buildings | A buildings GeoDataFrame: polygons, a CRS and a column of heights in metres | One RASTER of heights in metres |

## Raster Calculator

A Python node whose code is written for it when it is dropped: input_0 minus
input_1, with its other operations listed above it, statistics among them.
Return another call to change what it does:

| Call | Result |
|---|---|
| `curio_raster_calculate("add", [input_0, input_1])` | input_0 plus input_1, cell by cell; also `"subtract"`, `"multiply"` and `"divide"` |
| `curio_raster_calculate("choose", [input_0, input_1, input_2], codes=[21, 31])` | input_1 where input_0's class is one of the codes, input_2 elsewhere |
| `curio_raster_statistics(input_0)` | the `mean`, `median`, `min`, `max` and `count` of the raster's cells with a value, as a table of one row |
| `curio_raster_statistics(input_0, mask=input_1, mask_values=[0])` | the same over the cells where a second raster on input_1, on the same grid, is 0 |

A cell with no value in an input an operation reads has no value in the result,
and rasters on different grids are refused. The
[Rasters section of the usage guide](../../docs/USAGE.md#rasters) lists every
option.

## Rasterize Buildings

### Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Height column (`attribute`) | `height` | The column the heights are read from |
| Zoom level (`zoom`) | `16` | The zoom level of the map tiles |
| Maximum height (`max_height`) | `550` m | The height drawn as gray level 255 |

Deep Umbra reads zoom-16 tiles where 255 is 550 m.

### Output

The tiles side by side in one GeoTIFF in EPSG:3395 (World Mercator), one band of
heights in metres. Each tile is 256 by 256 cells of 8-bit gray, drawn between
the tile's corners, as SCOUT writes `<zoom>_<x>_<y>.png`, and each gray level is
the maximum height over 255 (2.16 m at 550 m). An Autark map draws it as
`input_0`:

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
```

A tile is written when a building is near it. A tile that is not written is no
data (NaN, the file's no-data value): a map leaves it out, and so do a Raster
Calculator's statistics and Accumulated Shadow. Inside a written tile, every pixel with no
building is 0, the ground. A building with no value in the height column adds
nothing, and a building taller than the maximum height is drawn at the maximum.

## A dataflow

```
[ Buildings ] ──► [ Rasterize Buildings ] ──► [ Accumulated Shadow ] ──► [ Autark: map of the shadow ]
                            │                          │
                            └──── mask ──► [ Raster Calculator ] ◄──┘
```

[Example 24](../../docs/examples/24-scout-shadow-model-chicago-loop.md) holds this
dataflow, on SCOUT's Chicago Loop buildings from the Data Catalog, with a map of
the heights too: Accumulated Shadow runs Deep Umbra on the heights, and the
Raster Calculator takes the shadow's statistics over the ground, the heights as
its mask. The test dataflow
[Quad Cities flood depth, nature-based solutions and vulnerability](../../docs/examples/dataflows/quad-cities-flood-vulnerability.json)
chooses SCOUT's flood depth by nature-based solution class with a Raster
Calculator and takes its statistics with another.

## Setup

Curio installs the package's Python libraries with it: `datashader`,
`spatialpandas`, `dask`, `rasterio`, `geopandas`, `numpy`, `pandas`, `pillow`,
`pyarrow`, `pyproj` and `shapely`. It is installed for you when Curio starts
with `--with-examples`; otherwise add it from the Node Catalog.
