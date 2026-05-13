# Docs

## Usage

- [Installation and usage](USAGE.md)
- [Quick start](QUICK-START.md)
- [Deployment](DEPLOYMENT.md)

## Making contributions

- [Contributing to Curio](CONTRIBUTING.md)
- [Onboarding for undergraduate students](ONBOARDING.md)
- [System architecture](ARCHITECTURE.md)

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
| 06 | [Autark what-if shadow study](examples/06-autark-what-if-shadow-study.md) | Criterion-driven what-if (tall buildings); side-by-side baseline / modified maps via direct `AUTK_COMPUTE` fan-out | Boston Back Bay building-height shadow study | 🔴 |
| 07 | [Autark GPU shader](examples/07-autark-gpu-shader.md) | WGSL shader executed via `AUTK_COMPUTE`; brushable `AUTK_PLOT` ↔ `AUTK_MAP` | Chicago Loop shadow | 🔴 |
| 08 | [Autark spatial join + regression](examples/08-autark-spatial-join-regression.md) | DuckDB spatial join in `JS_COMPUTATION` + per-feature OLS GPU regression + linked Autark scatter | Niterói land-surface temperature warming | 🔴 |
| 09 | [Heterogeneous data + linked views](examples/09-heterogeneous-data-linked-views.md) | Cross-grammar Autark ↔ Vega-Lite brushing on raster + tabular + GeoJSON merged via `MERGE_FLOW` and fanned out via `DATA_POOL` | Milan urban heat exposure (UTCI) | 🔴 |
| 10 | [Street-level computer vision](examples/10-street-vision-cv-analysis.md) | `STREET_VISION` and `CV_ANALYSIS` nodes: HuggingFace segmentation/detection over Google Street View imagery, neighborhood enrichment, linked Vega-Lite map + bar views | Chicago Lincoln Park greenery | 🟡 |
