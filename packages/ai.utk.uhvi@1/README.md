# `ai.utk.uhvi@1`: fixture package

A minimal package used to exercise the Curio node-catalog integration end-to-end
(see [`docs/NODE-CATALOG.md`](../../docs/NODE-CATALOG.md) for the user-facing guide,
[`docs/EXTENDING.md`](../../docs/EXTENDING.md) for package authoring, and
[`docs/schemas/node-package.v4.json`](../../docs/schemas/node-package.v4.json) for the manifest schema).

It registers three kinds that together form a complete UHVI workflow:

| Canonical id | Engine | Editor | Purpose |
|--------------|--------|--------|---------|
| `ai.utk.uhvi/uhvi-load@1`  | python | code | Load a UHVI raster from disk. |
| `ai.utk.uhvi/uhvi-zones@1` | python | code | Load a polygon GeoDataFrame (e.g. census tracts) to use as the zonal footprint. |
| `ai.utk.uhvi/uhvi-zonal@1` | python | code | Zonal-mean UHVI over the polygon GeoDataFrame. |

### Demo wiring

```
[ UHVI Loader ] ──raster──┐
                          ├──► [ UHVI Zonal Stats ] ──► (GeoDataFrame with uhvi_mean)
[ UHVI Zones  ] ──gdf────┘
```

The zonal node takes the raster and the zones GeoDataFrame on its two input
circles, in either order: its code tells them apart by type.

The defaults assume a workspace layout matching the repo root:
`./milan/Milan_Tmrt_2022_203_1200D.tif` and
`./milan/R03_21-11_WGS84_P_SocioDemographics_MILANO_Selected.shp`.
