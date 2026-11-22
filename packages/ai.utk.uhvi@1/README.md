# `ai.utk.uhvi@1`: fixture package

A minimal package used to exercise the Curio node-catalog integration end-to-end
(see [`docs/NODE-CATALOG.md`](../../docs/NODE-CATALOG.md) for the user-facing guide,
[`docs/EXTENDING.md`](../../docs/EXTENDING.md) for package authoring, and
[`docs/schemas/node-package.v4.json`](../../docs/schemas/node-package.v4.json) for the manifest schema).

It registers three kinds that together form a complete UHVI workflow:

| Canonical id | Engine | Editor | Purpose |
|--------------|--------|--------|---------|
| `ai.utk.uhvi/uhvi-load@1`  | python | code | Load a UHVI raster from the Data Catalog. |
| `ai.utk.uhvi/uhvi-zones@1` | python | code | Load polygons (e.g. census tracts) from the Data Catalog to use as the zonal footprint. |
| `ai.utk.uhvi/uhvi-zonal@1` | python | code | Zonal-mean UHVI over the polygon GeoDataFrame. |

### Functions

UHVI Zonal Stats' code is the call of one function, which does its work:

| Function | Module | What it does |
|---|---|---|
| `zonal_mean(first, second)` | `uhvi_statistics`, this package's | The mean of a raster's first band under each polygon of a GeoDataFrame, as the polygons' `uhvi_mean`; the raster and the polygons come in either order |

```python
from uhvi_statistics import zonal_mean

return zonal_mean(input_0, input_1)
```

### Demo wiring

```
[ UHVI Loader ] ──raster──┐
                          ├──► [ UHVI Zonal Stats ] ──► (GeoDataFrame with uhvi_mean)
[ UHVI Zones  ] ──gdf────┘
```

The zonal node takes the raster and the zones GeoDataFrame on its two input
circles, in either order: `zonal_mean` tells them apart by type.

UHVI Loader and UHVI Zones each read the Data Catalog dataset their widget
holds, Raster or Zones: drop a dataset or a file on the node, or choose a file
in its Widgets tab. Each one's code is that read, such as UHVI Loader's
`return curio_load_data([!! raster !!])`.
