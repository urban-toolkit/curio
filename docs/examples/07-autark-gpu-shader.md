# Autark GPU shader

A single `autk-grammar` node that runs a WGSL shadow-accumulation shader on the GPU and renders the
result as a thematic map linked to a brushable histogram. The driving question: *how many minutes of
shadow does one Chicago Loop building cast onto each surrounding road segment over a June day?*

It is a translation of the upstream Autark shadow use case
([github.com/urban-toolkit/autark/.../usecases/src/shadows](https://github.com/urban-toolkit/autark/tree/main/usecases/src/shadows))
into a single grammar spec.

!!! note "WebGPU required"
    Autark relies on WebGPU. Run this example in a Chromium-based browser (Chrome / Edge) on a machine
    with a working GPU stack.

## What it demonstrates

- **GPU compute in the grammar**: the spec's `compute` block runs the real shadow shader. Each road's
  geometry is bound as a per-feature matrix (`attributes.seg` = `geometry.coordinates`,
  `attributeMatrices.seg`), the casting building's footprint as a `uniformMatrices.ring`, and
  `uniforms` carry `bld_height` and `doy` (172 = June solstice). The shader walks daylight hours
  07:00–19:00, builds an oriented shadow box per hour, tests each road segment, and accumulates
  minutes into a single `shadow` output column.
- **Local PBF loading**: OSM comes from `docs/examples/data/chicago_loop.osm.pbf` (no Overpass at run
  time). The grammar loads it in EPSG:3395, so the shader's metric geometry math holds.
- **Linked views**: roads are coloured by `compute.shadow`; a brushable histogram (`plot`, `brushX`,
  13 bins) is linked back to the map via `mapRef`.

## Nodes

| Node | Type | Role |
|------|------|------|
| shadow grammar | `autk-grammar` | Load Chicago Loop from PBF → shadow shader (`compute`) → thematic map + brushable histogram |

## Why the footprint is baked in

A declarative spec can't run JavaScript to pick "the first building," so the casting building's outer
ring is supplied directly as `uniformMatrices.ring` (a representative Loop building, in EPSG:3395) with
its `bld_height`. Swap those values to cast from a different building. Set `uniforms.doy` to `265`
(September) or `355` (December) to change the season.

## Data

`docs/examples/data/chicago_loop.osm.pbf` — OSM extract for the Chicago Loop (regenerate with
`scripts/build_example_pbfs.py`).
