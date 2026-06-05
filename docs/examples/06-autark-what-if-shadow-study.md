# Autark what-if shadow study

A criterion-driven what-if for Boston's Back Bay: buildings whose **footprint area exceeds 200 m²** are
raised by 3× in a modified scenario, rendered side-by-side with the baseline. Two `autk-grammar` nodes
load the same local PBF independently so you can compare the two maps.

!!! note "WebGPU required"
    Autark relies on WebGPU. Run this example in a Chromium-based browser (Chrome / Edge) on a machine
    with a working GPU stack.

## What it demonstrates

- **Geometry-derived GPU compute**: the modified node's `compute` block binds each building's outer
  ring as a per-feature matrix (`attributes.ring` = `geometry.coordinates.0`, `attributeMatrices.ring`)
  and computes its footprint **area** on the GPU with a shoelace sum. Buildings load in EPSG:3395, so
  the area is in m²; those over 200 m² get `height × 3` written to the `height_mod` output column.
- **Baseline vs modified**: the baseline node colours buildings by their original `height`; the
  modified node colours by `compute.height_mod`. Side-by-side, the raised buildings stand out.
- **Local PBF loading**: OSM comes from `docs/examples/data/back_bay.osm.pbf` — no Overpass at run time.

## Nodes

| Node | Type | Role |
|------|------|------|
| baseline | `autk-grammar` | Load Back Bay from PBF; map buildings by original `height` |
| modified | `autk-grammar` | Load Back Bay from PBF; GPU footprint-area criterion → ×3; map by `compute.height_mod` |

The two nodes are independent (no edge): each loads the PBF and renders its own map. Height is the
what-if proxy that's directly visible on the map; swap the multiplier compute step for the WGSL shadow
shader in [Example 7](07-autark-gpu-shader.md) for a full shadow study.

## Data

`docs/examples/data/back_bay.osm.pbf` — OSM extract for Boston's Back Bay (regenerate with
`scripts/build_example_pbfs.py`).
