# `scout.raster-conversion@1`: SCOUT Raster Conversion

SCOUT's building rasterizer ("OSM vector to raster"), ported from
[SCOUT](https://github.com/urban-toolkit/scout) (`backend/compute/raster_conversion`).
SCOUT's `convert_raster` draws each building's height into map tiles, the input of
SCOUT's Deep Umbra shadow model; the node joins the tiles into one raster an Autark
map draws.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.raster-conversion/rasterize-buildings` | Rasterize Buildings | A buildings GeoDataFrame: polygons, a CRS and a `height` column in metres | One RASTER: the height mosaic |

## Settings

The node's **Widgets** tab holds its settings, SCOUT's `convert_raster` parameters:

| Widget | Default | What it sets |
|---|---|---|
| Height column (`attribute`) | `height` | SCOUT's `attribute`. SCOUT rasterizes `height` only; for another name it prints `Feature '<name>' not supported for layer` and writes no tiles |
| Zoom level (`zoom`) | `16` | The zoom level of the map tiles |
| Maximum height (`max_height`) | `550` m | The height drawn as gray level 255 |

Deep Umbra reads zoom-16 tiles where 255 is 550 m.

## SCOUT's code

`sources/scout_raster_conversion/convert_to_raster.py` is SCOUT's
`backend/compute/raster_conversion/scripts/convert_to_raster.py` (commit `b98369e5`)
as SCOUT wrote it, with 7 lines changed, each marked `# Curio:`:

- `import pygeos` and its three calls (`get_parts`, `get_rings`, `get_coordinates`)
  are shapely 2's: pygeos was merged into shapely 2 and has no Python 3.12 build.
- `source.geometry.array.data` is `np.asarray(source.geometry.array)`: geopandas 1
  has no `.data`.
- `convert_raster` takes `max_height` (default 550) and passes it where SCOUT passes 550.

On SCOUT's Chicago Loop buildings, its tiles are byte for byte the ones SCOUT's own
environment (Python 3.9, pygeos, OpenCV 4.7) writes.

The node writes the buildings to a GeoJSON file, calls `convert_raster` on it, and
hands the folder of tiles SCOUT writes (`<zoom>_<x>_<y>.png`) to `mosaic`.

## Output

`sources/scout_raster_conversion/mosaic.py`, Curio's own code, puts the tiles side by
side in one GeoTIFF in EPSG:3395 (World Mercator), each where SCOUT's `compute_tile`
drew it. One band of heights in metres: a gray level times the maximum height over
255 (2.16 m at 550 m). A tile SCOUT did not write, because no building is near it, is
0, the ground. An Autark map draws it as `input_0`:

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
```

Accumulated Shadow (`scout.shadow@1`) reads it too.

## A dataflow

```
[ Data Loading: buildings ] ──► [ Rasterize Buildings ] ──► [ Autark: map of the mosaic ]
```

The test dataflow [BuildingRasters](../../docs/examples/dataflows/BuildingRasters.json)
is this dataflow, on twelve buildings built in code.

## Setup

Curio installs the package's Python libraries with it: `datashader`,
`spatialpandas`, `dask`, `rasterio`, `matplotlib` and `opencv-python-headless`. It is
installed for you when Curio starts with `--with-examples`.
