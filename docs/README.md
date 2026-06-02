# Docs

## Usage

- [Installation and usage](USAGE.md)
- [Quick start](QUICK-START.md)
- [Node catalog](CATALOG.md)
- [Real-time collaboration](COLLABORATION.md)
- [Deployment](DEPLOYMENT.md)

## Making contributions

- [Contributing to Curio](CONTRIBUTING.md)
- [Onboarding for undergraduate students](ONBOARDING.md)
- [System architecture](ARCHITECTURE.md)
- [Extending Curio with new node packages](EXTENDING.md)

## Examples

Each example below has a JSON dataflow you can import into Curio plus a step-by-step markdown walkthrough. Pipeline overviews in the walkthroughs are drawn with [Mermaid](https://mermaid.js.org/) `flowchart` blocks, which GitHub renders inline.

The same examples are also seeded into the public deployments at [**curio.urbantk.org**](https://curio.urbantk.org) (stable) and [**curio-dev.urbantk.org**](https://curio-dev.urbantk.org) (latest `main`) — sign in to fork them into your own projects, or browse them read-only as a guest.

Icons indicate the complexity level of each example: 🟢 Easy, 🟡 Intermediate, 🔴 Advanced.

| # | Example | Functionality | Use case | Complexity |
|---|---|---|---|---|
| 01 | [Vega-Lite chained transforms](examples/01-vega-lite-chained-transforms.md) | Multiple Vega-Lite views fed from a chain of `DATA_TRANSFORMATION` cleanups | Sidewalk accessibility (Project Sidewalk, Chicago) | 🟢 |
| 02 | [Vega-Lite spatial density](examples/02-vega-lite-spatial-density.md) | Spatial density + zip-code aggregation in Vega-Lite, fan-out via `DATA_POOL` | Chicago green roofs | 🟢 |
| 03 | [Vega-Lite linked temporal charts](examples/03-vega-lite-linked-temporal-charts.md) | Temporal aggregation feeding linked bar + line Vega-Lite views | Chicago speed-camera violations | 🟡 |
| 04 | [Vega-Lite multi-flow dashboard](examples/04-vega-lite-multi-flow-dashboard.md) | Multiple independent dataflows joined via `MERGE_FLOW` into one coordinated dashboard | Chicago red-light violations | 🟡 |
| 05 | [Vega-Lite multi-view drilldown](examples/05-vega-lite-multi-view-drilldown.md) | Five parallel dataflows producing a faceted Vega-Lite drill-down across orthogonal axes | Chicago building energy use | 🟡 |
| 06 | [Autark what-if shadow study](examples/06-autark-what-if-shadow-study.md) | Two `autk-grammar` nodes for baseline vs modified scenario; GPU compute raises tall buildings by 3× | Boston Back Bay building-height shadow study | 🔴 |
| 07 | [Autark GPU shader](examples/07-autark-gpu-shader.md) | `autk-grammar` with WGSL `wglsFunction` normalising lane count per road; thematic map + brushable histogram | Chicago Loop road capacity | 🔴 |
| 08 | [Autark spatial join + regression](examples/08-autark-spatial-join-regression.md) | `autk-grammar` grammar-native spatial join (roads × buildings, 100 m NEAR) + GPU compute + linked scatter | Niterói road capacity vs nearby building height | 🔴 |
| 09 | [Heterogeneous data + linked views](examples/09-heterogeneous-data-linked-views.md) | Python UTCI pipeline fanned out via `DATA_POOL`; `autk-grammar` map + Vega-Lite scatter with bidirectional brushing | Milan urban heat exposure (UTCI) | 🔴 |
| 10 | [Street-level computer vision](examples/10-street-vision-cv-analysis.md) | `curio.streetvision@1` Fetcher → HF Inference → Gallery → `Spatial Join` → Vega-Lite polygons + bars | Chicago Lincoln Park greenery audit | 🔴 |
| 11 | [Autark PBF loading](examples/11-autark-pbf-loading.md) | Single `autk-grammar` node loading OSM layers from a local `.pbf` file; all parsing in the browser via DuckDB-WASM | Lower Manhattan (Battery Park City + Financial District) | 🟢 |
