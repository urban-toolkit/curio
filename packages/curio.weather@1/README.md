# `curio.weather@1`: Weather Analysis

Nodes for weather data ingestion and thermal-comfort analysis: ERA5 meteorological
loading, UTCI computation via `pythermalcomfort`, raster I/O via `rasterio`, raster
zonal statistics via `rasterstats`, and census/polygon reprojection.

This package backs the [Heterogeneous data + linked views](../../docs/examples/09-heterogeneous-data-linked-views.md)
example (Milan urban heat exposure). It is auto-seeded when Curio starts with
`--with-examples` / `--deploy`, because that seeded workflow needs its Python
dependencies.

## Kinds

| Canonical id | Category | Label | Purpose |
|---|---|---|---|
| `curio.weather/mrt-load` | data | Milan MRT Loader | Open the `data.urbanlab.milan-mrt` GeoTIFF from the Data Catalog and return the rasterio dataset. |
| `curio.weather/weather-load` | data | ERA5 Milan Weather | Load `data.urbanlab.milan-era5-weather` from the Data Catalog (Td / Wind / RH per hour). |
| `curio.weather/census-load` | data | Milan Census Polygons | Load `data.urbanlab.milan-census-gt65` from the Data Catalog as a GeoDataFrame. |
| `curio.weather/utci-compute` | computation | UTCI from raster + weather | Per-pixel Universal Thermal Climate Index via `pythermalcomfort`. |
| `curio.weather/utci-zonal` | computation | UTCI Zonal Mean | `rasterstats.zonal_stats` of the UTCI grid into census polygons. |
| `curio.weather/census-reproject` | computation | Reproject census to EPSG:3395 | Reproject from UTM 32632 to the projection `AUTK_MAP` expects; tag as `census`. |
| `curio.weather/gt65-projection` | computation | Project gt_65 column | Project down to `gt_65` for an independent boxplot view. |

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

Multi-input nodes read their edges positionally (`arg[0]`, `arg[1]`, …) using the
`MERGE_FLOW` pattern, so **wiring order matters**. `utci-compute` expects
(raster, weather DataFrame); `utci-zonal` expects (raster, UTCI tuple, polygons).

## Setup

Install the package from the [Node Catalog](../../docs/NODE-CATALOG.md). The drawer
inside the canvas (**Node Catalog → Browse Node Catalog +**) or the **Nodes** tab on
`/catalog`. Curio installs the declared Python dependencies automatically:

- `pythermalcomfort ^3.9`
- `rasterio >=1.5.0`
- `rasterstats ^0.20`

The package declares the `filesystem.read` permission; the loader nodes read their
inputs from paths relative to the Curio launch directory, so adjust those paths in
the node source if your data lives elsewhere.
