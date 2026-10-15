# `scout.raster-conversion@1`: SCOUT Raster Conversion

SCOUT's building rasterizer ("OSM vector to raster"), ported from
[SCOUT](https://github.com/urban-toolkit/scout) (`backend/compute/raster_conversion`).
It draws each building's height into map tiles and joins the tiles into one
raster, which an Autark map draws and SCOUT's Deep Umbra shadow model reads.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.raster-conversion/rasterize-buildings` | Rasterize Buildings | A buildings GeoDataFrame: polygons, a CRS and a column of heights in metres | One RASTER of heights in metres |

## Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Height column (`attribute`) | `height` | The column the heights are read from |
| Zoom level (`zoom`) | `16` | The zoom level of the map tiles |
| Maximum height (`max_height`) | `550` m | The height drawn as gray level 255 |

Deep Umbra reads zoom-16 tiles where 255 is 550 m.

## Output

The tiles side by side in one GeoTIFF in EPSG:3395 (World Mercator), one band of
heights in metres. Each tile is 256 by 256 cells of 8-bit gray, drawn between
the tile's corners, as SCOUT writes `<zoom>_<x>_<y>.png`, and each gray level is
the maximum height over 255 (2.16 m at 550 m). An Autark map draws it as
`input_0`:

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
```

A tile is written when a building is near it. A tile that is not written is no
data (NaN, the file's no-data value): a map leaves it out, and so do Raster
Statistics and Accumulated Shadow. Inside a written tile, every pixel with no
building is 0, the ground. A building with no value in the height column adds
nothing, and a building taller than the maximum height is drawn at the maximum.

## A dataflow

```
[ Data Loading: buildings ] ──► [ Rasterize Buildings ] ──► [ Autark: map of the heights ]
```

The test dataflow [BuildingRasters](../../docs/examples/dataflows/BuildingRasters.json)
is this dataflow, on twelve buildings built in code.

## Setup

Curio installs the package's Python libraries with it: `datashader`,
`spatialpandas`, `dask`, `rasterio`, `geopandas`, `numpy`, `pandas`, `pillow`,
`pyarrow`, `pyproj` and `shapely`. It is installed for you when Curio starts
with `--with-examples`.
