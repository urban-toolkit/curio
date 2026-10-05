# `scout.raster-conversion@1`: SCOUT Raster Conversion

SCOUT's building rasterizer ("OSM vector to raster"), ported from
[SCOUT](https://github.com/urban-toolkit/scout) (`backend/compute/raster_conversion`).
It draws each building's height into map tiles, the input of SCOUT's Deep Umbra
shadow model, and joins the tiles into one raster an Autark map draws.

## Nodes

| Canonical id | Label | Input | Output |
|---|---|---|---|
| `scout.raster-conversion/rasterize-buildings` | Rasterize Buildings | A buildings GeoDataFrame: polygons, a CRS and a column of heights in metres | `(mosaic, tiles)`: one RASTER and one table |

## Settings

The node's **Widgets** tab holds its settings:

| Widget | Default | What it sets |
|---|---|---|
| Height column (`attribute`) | `height` | The column the heights are read from |
| Zoom level (`zoom`) | `16` | The zoom level of the map tiles |
| Maximum height (`max_height`) | `550` m | The height drawn as gray level 255 |

Deep Umbra reads zoom-16 tiles where 255 is 550 m.

## Outputs

- **mosaic**: the tiles side by side in one GeoTIFF in EPSG:3395 (World Mercator),
  one band of heights in metres: each gray level is the maximum height over 255
  (2.16 m at 550 m). An Autark map draws it as `input_0`:

  ```json
  {"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
  ```

- **tiles**: one row per tile, with `zoom`, `x`, `y` and `png`, the tile's PNG file
  in base64: 256 by 256 pixels of 8-bit gray, drawn in EPSG:3395 between the
  tile's corners and named `<zoom>_<x>_<y>.png` in SCOUT.

A tile is written when a building is near it. In the mosaic, the area of a tile
that is not written is 0, the ground, and so is every pixel with no building. A
building with no value in the height column adds nothing, and a building taller
than the maximum height is drawn at the maximum.

## A dataflow

```
[ Data Loading: buildings ] ──► [ Rasterize Buildings ] ──► [ Autark: map of the mosaic ]
```

The test dataflow [BuildingRasters](../../docs/examples/dataflows/BuildingRasters.json)
is this dataflow, on four buildings built in code.

## Setup

Curio installs the package's Python libraries with it: `datashader`,
`spatialpandas`, `dask` and `rasterio`. It is installed for you when Curio
starts with `--with-examples`.
