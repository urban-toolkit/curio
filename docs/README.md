# Docs

## Usage

- [Installation and usage](USAGE.md)
- [Quick start](QUICK-START.md)
- [Authoring nodes](AUTHORING-NODES.md): build your own node, from a clone to a shareable package
- [Node catalog](NODE-CATALOG.md)
- [Data catalog](DATA-CATALOG.md)
- [Agent catalog](AGENT-CATALOG.md): browse, add, and attach Curio's AI agents, and write your own
- [Real-time collaboration](COLLABORATION.md)
- [Deployment](DEPLOYMENT.md)
- [Upgrading](UPGRADING.md): what changes for an existing deployment, and what to do about it

## Making contributions

- [Contributing to Curio](CONTRIBUTING.md)
- [Onboarding for undergraduate students](ONBOARDING.md)
- [System architecture](ARCHITECTURE.md)
- [Trill dataflow specification](TRILL-SPEC.md): the JSON format a saved dataflow is stored in
- [Extending Curio with new node packages](EXTENDING.md)

## Examples

Each example below has a JSON dataflow you can import into Curio plus a step-by-step markdown walkthrough. Pipeline overviews in the walkthroughs are drawn with [Mermaid](https://mermaid.js.org/) `flowchart` blocks, which GitHub renders inline.

The same examples are also seeded into the public deployments at [**curio.urbantk.org**](https://curio.urbantk.org) (stable) and [**curio-dev.urbantk.org**](https://curio-dev.urbantk.org) (latest `main`). Sign in to fork them into your own projects, or browse them read-only as a guest.

Every example reads its inputs from the [Data Catalog](DATA-CATALOG.md): the datasets ship in `<repo_root>/datasets/` and each dataflow declares the ones it needs, so the loader nodes address them by id with `curio_dataset_path("<id>")` rather than by a path into this repo. The four Autark examples (06, 07, 08, 11) are the exception, still reading a committed `.osm.pbf` by relative path, because the browser fetches those bytes directly and `.pbf` is not a catalog format.

Icons indicate the complexity level of each example: 🟢 Easy, 🟡 Intermediate, 🔴 Advanced.

| # | Example | Functionality | Use case | Complexity |
|---|---|---|---|---|
| 01 | [Vega-Lite chained transforms](examples/01-vega-lite-chained-transforms.md) | Multiple Vega-Lite views fed from a chain of `Data Transformation` cleanups | Sidewalk accessibility (Project Sidewalk, Chicago) | 🟢 |
| 02 | [Vega-Lite spatial density](examples/02-vega-lite-spatial-density.md) | Spatial density + zip-code aggregation in Vega-Lite, fan-out via `Data Pool` | Chicago green roofs | 🟢 |
| 03 | [Vega-Lite linked temporal charts](examples/03-vega-lite-linked-temporal-charts.md) | Temporal aggregation feeding linked bar + line Vega-Lite views | Chicago speed-camera violations | 🟡 |
| 04 | [Vega-Lite multi-flow dashboard](examples/04-vega-lite-multi-flow-dashboard.md) | Multiple independent dataflows joined via `Merge Flow` into one coordinated dashboard | Chicago red-light violations | 🟡 |
| 05 | [Vega-Lite multi-view drilldown](examples/05-vega-lite-multi-view-drilldown.md) | Five parallel dataflows producing a faceted Vega-Lite drill-down across orthogonal axes | Chicago building energy use | 🟡 |
| 06 | [Autark what-if shadow study](examples/06-autark-what-if-shadow-study.md) | Two `autk-grammar` nodes (baseline vs modified); GPU shoelace footprint-area criterion (>200 m²) raises tall buildings 3× | Boston Back Bay building-height what-if | 🔴 |
| 07 | [Autark GPU shader](examples/07-autark-gpu-shader.md) | `autk-grammar` with a WGSL shadow-accumulation shader (minutes of shadow per road); thematic map + brushable histogram | Chicago Loop solstice shadows | 🔴 |
| 08 | [Autark spatial join + regression](examples/08-autark-spatial-join-regression.md) | `autk-grammar` loads roads from PBF, a Python node samples a 24-band LST raster, then GPU per-road OLS regression + linked scatter | Niterói per-road warming trend (2001 to 2024) | 🔴 |
| 09 | [Heterogeneous data + linked views](examples/09-heterogeneous-data-linked-views.md) | Python UTCI pipeline fanned out via `Data Pool`; `autk-grammar` map + Vega-Lite scatter with bidirectional brushing | Milan urban heat exposure (UTCI) | 🔴 |
| 10 | [Street-level computer vision](examples/10-street-vision-cv-analysis.md) | `curio.streetvision@1` Fetcher → HF Inference → Gallery, joined against `Data Loading` → `Data Transformation` polygons via `Spatial Join` → Vega-Lite map + bars | Chicago Lincoln Park greenery audit | 🔴 |
| 11 | [Autark PBF loading](examples/11-autark-pbf-loading.md) | Single `autk-grammar` node loading OSM layers from a local `.pbf` file; all parsing in the browser via DuckDB-WASM | Lower Manhattan (Battery Park City + Financial District) | 🟢 |
