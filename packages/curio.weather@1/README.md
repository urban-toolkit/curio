# `curio.weather@1`: Weather Analysis

Nodes for weather data ingestion and thermal-comfort analysis: ERA5 meteorological
loading, UTCI computation via `pythermalcomfort`, raster I/O via `rasterio`, raster
zonal statistics via `rasterstats`, and census/polygon reprojection.

This package backs the [Heterogeneous data + linked views](../../docs/examples/09-heterogeneous-data-linked-views.md)
example (Milan urban heat exposure). It is auto-seeded when Curio starts with
`--with-examples`, because that seeded workflow needs its Python
dependencies.

## Kinds

| Canonical id | Category | Label | Purpose |
|---|---|---|---|
| `curio.weather/mrt-load` | data | Milan MRT Loader | Open the `data.utk.milan-mrt` GeoTIFF from the Data Catalog and return the rasterio dataset. |
| `curio.weather/weather-load` | data | ERA5 Milan Weather | Load `data.utk.milan-era5-weather` from the Data Catalog (Td / Wind / RH per hour). |
| `curio.weather/census-load` | data | Milan Census Polygons | Load `data.utk.milan-census-gt65` from the Data Catalog as a GeoDataFrame. |
| `curio.weather/utci-compute` | computation | UTCI from raster + weather | Per-pixel Universal Thermal Climate Index via `pythermalcomfort`. |
| `curio.weather/utci-zonal` | computation | UTCI Zonal Mean | `rasterstats.zonal_stats` of the UTCI grid into census polygons. |
| `curio.weather/census-reproject` | computation | Reproject census to EPSG:3395 | Reproject from UTM 32632 to EPSG:3395; tag as `census`. |
| `curio.weather/gt65-projection` | computation | Project gt_65 column | Project down to `gt_65` for an independent boxplot view. |

## Functions

The code of each computation node is its settings and the call of one
function, which does the node's work:

| Function | Module | What it does |
|---|---|---|
| `utci_grid(raster, weather, *, timestamp=12, upscale_factor=1.0)` | `weather_utci` | The Universal Thermal Climate Index of each cell of a mean radiant temperature raster, under the weather of the hour `timestamp`: `(grid, shape)` |
| `utci_zonal_mean(raster, utci, census)` | `weather_census` | The mean UTCI of each census polygon, with its geometry and `gt_65` |
| `reproject_census(census, *, source_crs=32632, target_crs=3395)` | `weather_census` | The census polygons in `target_crs`, those whose mean UTCI is not above 0 left out, named `census` |
| `gt65_column(census)` | `weather_census` | The census table cut to its `gt_65` column |

UTCI from raster + weather's code, for one:

```python
from weather_utci import utci_grid

TIMESTAMP = 12
UPSCALE_FACTOR = 1.0

return utci_grid(
    [!! input_0 !!], [!! input_1 !!],
    timestamp=TIMESTAMP, upscale_factor=UPSCALE_FACTOR,
)
```

## Demo wiring

```
[ Milan MRT Loader ]      ──raster──┬──► [ UTCI from raster + weather ] ──json──┐
[ ERA5 Milan Weather ]    ──df─────┘                                            │
                                                                                ▼
[ Milan Census Polygons ] ──gdf─────────────────────────────────────► [ UTCI Zonal Mean ]
                                                                                │
                                                          ┌─────────────────────┤
                                                          ▼                     ▼
                                        [ Reproject to EPSG:3395 ]   [ Project gt_65 column ]
```

Multi-input nodes read their input circles in order (`[!! input_0 !!]`,
`[!! input_1 !!]`, …), so **wiring order matters**. `utci-compute` expects
(raster, weather DataFrame); `utci-zonal` expects (raster, UTCI tuple, polygons).

## Setup

Install the package from the [Node Catalog](../../docs/NODE-CATALOG.md). The drawer
inside the canvas (**Node Catalog → Browse Node Catalog +**) or the **Nodes** tab on
`/catalog`. Curio installs the declared Python dependencies automatically:

- `geopandas >=1.1.3`
- `numpy >=1.26`
- `pandas >=3.0.2`
- `pythermalcomfort ^3.9`
- `rasterio >=1.5.0`
- `rasterstats ^0.20`

The package declares the `filesystem.read` permission; its loader nodes read the
Milan datasets from the Data Catalog.
