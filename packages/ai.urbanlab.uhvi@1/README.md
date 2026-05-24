# `ai.urbanlab.uhvi@1` — fixture package

A minimal package used to exercise the Curio nodes-warehouse integration end-to-end
(see `docs/nodesfactory@docs/manifest_spec.md`, `docs/nodesfactory@docs/frontend.md`, and `docs/nodesfactory@docs/overview.md`).

It registers three kinds that together form a complete UHVI workflow:

| Canonical id | Engine | Editor | Purpose |
|--------------|--------|--------|---------|
| `ai.urbanlab.uhvi/uhvi-load@1`  | python | code | Load a UHVI raster from disk. |
| `ai.urbanlab.uhvi/uhvi-zones@1` | python | code | Load a polygon GeoDataFrame (e.g. census tracts) to use as the zonal footprint. |
| `ai.urbanlab.uhvi/uhvi-zonal@1` | python | code | Zonal-mean UHVI over the polygon GeoDataFrame. |

### Demo wiring

```
[ UHVI Loader ] ──raster──┐
                          ├──► [ UHVI Zonal Stats ] ──► (GeoDataFrame with uhvi_mean)
[ UHVI Zones  ] ──gdf────┘
```

The zonal node receives the raster as `arg[0]` and the zones GeoDataFrame
as `arg[1]`. Wire the raster edge **first** so it lands at index 0; Curio
preserves wiring order on multi-edge ports.

The defaults assume a workspace layout matching the repo root:
`./milan/Milan_Tmrt_2022_203_1200D.tif` and
`./milan/R03_21-11_WGS84_P_SocioDemographics_MILANO_Selected.shp`.

## Self-containment

The package is **self-contained** — every template preset lives under
`templates/<kindId>/` inside this directory. It does **not** reference
`<CURIO_LAUNCH_CWD>/templates/` or any other path outside its own root.

## Seeding into a developer's package store

The backend ships a small dev-only seeder
(`utk_curio.backend.app.packages.seed_dev_packageages`) that copies this fixture
into `.curio/users/guest/packages/ai.urbanlab.uhvi@1/` on backend startup in
development. The seeder also refreshes the runtime copy when this
fixture has been edited since the last seed (mtime check), so spike-time
template tweaks land without a manual `rm -rf`. Set
`CURIO_RESEED_PACKAGES=1` to force a refresh.

The runtime copy is gitignored (`.curio/` is in the top-level
`.gitignore`); this fixture is the source of truth.
