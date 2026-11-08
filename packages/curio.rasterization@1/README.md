# `curio.rasterization@1`: Rasterization

SCOUT's raster nodes in Curio, ported from
[SCOUT](https://github.com/urban-toolkit/scout). The **Raster Calculator** runs
one operation over rasters on one grid, cell by cell or a raster's statistics.
**Rasterize Buildings** is SCOUT's building rasterizer ("OSM vector to raster",
`backend/compute/raster_conversion`): it draws each building's height into map
tiles and joins the tiles into one raster, which an Autark map draws and SCOUT's
Deep Umbra shadow model reads.

Once the package is in a dataflow (**Add to project** in the Node Catalog
drawer), its two nodes are under **Rasterization** in the Tools panel's **Node
Catalog** dropdown.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `curio.rasterization/raster-calculator` | Raster Calculator | One to three RASTERs on one grid, one per input circle; a GeoDataFrame on a circle is a layer its code reads as zones or a mask, and a JSON value one its code reads as it is, such as a region's corners | One RASTER, or a DATAFRAME of one row of statistics |
| `curio.rasterization/rasterize-buildings` | Rasterize Buildings | A buildings GeoDataFrame: polygons, a CRS and a column of heights in metres | One RASTER of heights in metres |

## Raster Calculator

A Python node that opens with the package's starter,
[`sources/raster-calculator.py`](sources/raster-calculator.py), when it is
dropped: input_0 minus input_1, with its other operations listed above it,
statistics among them. Its code imports them from the package's module:

```python
from scout_rasters.raster_algebra import raster_calculate, raster_statistics

return raster_calculate("subtract", [input_0, input_1], output_file=curio_output_file)
```

Return another call to change what it does:

| Call | Result |
|---|---|
| `raster_calculate("add", [input_0, input_1], output_file=curio_output_file)` | input_0 plus input_1, cell by cell; also `"subtract"`, `"multiply"` and `"divide"` |
| `raster_calculate("choose", [input_0, input_1, input_2], codes=[21, 31], output_file=curio_output_file)` | input_1 where input_0's class is one of the codes, input_2 elsewhere |
| `raster_calculate("subtract", [input_1, input_0], absolute=True, output_file=curio_output_file)` | the size of input_1 minus input_0: how much each cell changed, 0 where it did not; `absolute=True` takes the size of any operation's result |
| `raster_statistics(input_0)` | the `mean`, `median`, `min`, `max` and `count` of the raster's cells with a value, as a table of one row |
| `raster_statistics(input_0, mask=input_1, mask_values=[0])` | the same over the cells where a second raster on input_1, on the same grid, is 0 |

`raster_calculate` writes the raster it returns with `curio_output_file`, as
Rasterize Buildings writes its own. A cell with no value in an input an
operation reads has no value in the result, and rasters on different grids
are refused. An input circle also takes a layer, which the node's code reads
as zones or a mask, for example rasterized on a raster's grid with
`rasterio.features.rasterize`. The
[Rasters section of the usage guide](../../docs/USAGE.md#rasters) lists every
option.

### Raster math in another package

The functions are the package's module, `scout_rasters`: `raster_algebra`
holds the operations and the statistics, `web_tiles` the web map tile helpers
`tile_bounds` and `mosaic_web_tiles`, and `mosaic` the mosaics:

| Function | What it does |
|---|---|
| `mosaic_rasters(tiles, path, *, crs, dtype, ...)` | Rasters that lie on one grid side by side in one raster at `path`: a GDAL VRT that points at their files when every tile names its file, a GeoTIFF of their cells when every tile holds its cells |
| `mosaic_grid(tiles, resolution=None)` | The grid tiles make side by side, and where each tile's top-left cell lands on it |
| `mosaic_collection(tiles, output_file)` | A raster collection's rows side by side in one VRT that `output_file(name)` places, opened; it names the first way the tiles differ in CRS, resolution, bands, data type or no-data value |

A node of another package imports them when its package names Rasterization
in its manifest's `dependencies.packages`, as Deep Umbra
([`model.scout.deep-umbra@1`](../model.scout.deep-umbra@1/README.md)) does for
`tile_bounds` and `mosaic_rasters`, and Media
([`curio.media@1`](../curio.media@1/README.md)) for `mosaic_collection`, which
its Mosaic Rasters node calls:

```json
"dependencies": {"packages": {"curio.rasterization@1": "*"}}
```

A Python node of no package has none of them, so a raster step is a Raster
Calculator node.

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

## Dataflows

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
Calculator and takes its statistics with another. A third averages the depth
over the riverside tracts' land in each period: it reads the tracts and the
waterways, two layers, as zones and a mask.

## Skills

The package ships one skill for Curio's agents,
[`skills/rasterization/SKILL.md`](skills/rasterization/SKILL.md): which of its
nodes does what, the Raster Calculator's calls and its rules on grids, masks and
zones, and what Rasterize Buildings writes. Every agent on a dataflow that uses
Rasterization lists it, and a run that writes one of its two nodes is handed it
([a package's skills](../../docs/NODE-CATALOG.md#6-the-manifest)).

## Setup

Curio installs the package's Python libraries with it: `datashader`,
`spatialpandas`, `dask`, `rasterio`, `geopandas`, `numpy`, `pandas`, `pillow`,
`pyarrow`, `pyproj` and `shapely`. The raster nodes use them. The package is installed for you when Curio starts with
`--with-examples`; otherwise add it from the Node Catalog.
