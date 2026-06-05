# Autark spatial join + regression

Per-road warming trend over Niterói (2001–2024): combine OSM road geometry with a 24-band
land-surface-temperature (LST) raster and fit an **OLS regression per road on the GPU**. A Curio port of
the upstream Autark use case at
[github.com/urban-toolkit/autark/.../usecases/src/niteroi](https://github.com/urban-toolkit/autark/tree/main/usecases/src/niteroi).

!!! note "WebGPU required"
    Autark relies on WebGPU. Run this example in a Chromium-based browser (Chrome / Edge) on a machine
    with a working GPU stack.

!!! note "Network access required"
    The middle node downloads a 24-band GeoTIFF (~10 MB) from
    `https://raw.githubusercontent.com/urban-toolkit/autark/main/usecases/public/data/niteroi_lst_verao_2001_2024.tif`.
    It must be reachable when the dataflow runs.

## What it demonstrates

- **Grammar + Python split**: the regression runs in the grammar; the one step the grammar can't
  express — sampling a raster — stays in Python.
- **Array-attribute GPU compute**: the final `autk-grammar` node binds each road's 24-year LST series as
  a per-feature array (`attributes.bands` = `lst_timeseries`, `attributeArrays.bands` = 24) and runs the
  original OLS WGSL, emitting two columns (`angle` = warming angle in degrees, `intercept`). Roads are
  coloured by `compute.angle` and linked to a brushable `intercept`-vs-`angle` scatter.
- **Local PBF loading**: OSM roads come from `docs/examples/data/niteroi.osm.pbf` — no Overpass at run
  time.

## Nodes

| Node | Type | Role |
|------|------|------|
| niteroi-osm | `autk-grammar` | Load Niterói roads from the local PBF (EPSG:3395) and emit them downstream |
| niteroi-lst | `computation-analysis` (Python) | Fetch the 24-band LST raster; attach each road's per-year mean LST within 1 km as `lst_timeseries` (rasterstats) |
| niteroi-ols | `autk-grammar` | Per-road OLS regression on the GPU; thematic map + brushable scatter |

The raster sampling stays in Python because the grammar's data block has no raster source; everything
else — OSM loading, the regression, and the linked views — lives in the grammar.

## Data

`docs/examples/data/niteroi.osm.pbf` — OSM road extract for Niterói (regenerate with
`scripts/build_example_pbfs.py`). The LST raster is fetched at run time from the upstream Autark repo.
