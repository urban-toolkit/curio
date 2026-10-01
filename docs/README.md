# Docs

## Usage

- [Installation and usage](USAGE.md)
- [Quick start](QUICK-START.md)
- [Authoring nodes](AUTHORING-NODES.md): build your own node, from a clone to a shareable package
- [Node catalog](NODE-CATALOG.md): add, share, and publish node packages, and save a canvas node as one
- [Data catalog](DATA-CATALOG.md): import, reuse, and publish datasets, including your nodes' outputs
- [Agent catalog](AGENT-CATALOG.md): browse, add, and attach Curio's AI agents, and write your own
- [Discovery Catalog](DISCOVERY-CATALOG.md): search open data portals, and open folders, buckets and repositories, and bring their datasets into your Data Catalog
- [Real-time collaboration](COLLABORATION.md)
- [Deployment](DEPLOYMENT.md)

## Making contributions

- [Contributing to Curio](CONTRIBUTING.md)
- [Onboarding for undergraduate students](ONBOARDING.md)
- [System architecture](ARCHITECTURE.md)
- [Trill dataflow specification](TRILL-SPEC.md): the JSON format a saved dataflow is stored in
- [Extending Curio with new node packages](EXTENDING.md)

## Examples

Each example below has a JSON dataflow you can import into Curio plus a step-by-step markdown walkthrough. Pipeline overviews in the walkthroughs are drawn with [Mermaid](https://mermaid.js.org/) `flowchart` blocks, which GitHub renders inline.

The same examples are also seeded into the public deployments at [**flow.urbantk.org**](https://flow.urbantk.org) (stable) and [**dev.urbantk.org**](https://dev.urbantk.org) (latest `main`). Sign in to fork them into your own projects, or browse them read-only as a guest.

Every example reads its inputs from the [Data Catalog](DATA-CATALOG.md): the datasets ship in `<repo_root>/datasets/` and each dataflow declares the ones it needs, so the loader nodes address them by id with `curio_dataset_path("<id>")`, or `curio_collection("<id>")` for a collection. The storage examples (18 to 23) read datasets added from the **Example storage** source of the [Discovery Catalog](DISCOVERY-CATALOG.md). The four Autark examples (06, 07, 08, 11) read a committed `.osm.pbf` by relative path instead, because the browser fetches those bytes directly and `.pbf` is not a catalog format.

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
| 10 | [Street-level computer vision](examples/10-street-vision-cv-analysis.md) | `curio.streetvision@1` Fetcher → HF Inference → Simple View, joined against `Data Loading` → `Data Transformation` polygons via `Spatial Join` → Vega-Lite map + bars | Chicago Lincoln Park greenery audit | 🔴 |
| 11 | [Autark PBF loading](examples/11-autark-pbf-loading.md) | Single `autk-grammar` node loading OSM layers from a local `.pbf` file; all parsing in the browser via DuckDB-WASM | Lower Manhattan (Battery Park City + Financial District) | 🟢 |
| 12 | [Vega-Lite GeoDataFrame maps](examples/12-vega-lite-geodataframe-maps.md) | A `GeoDataFrame` drawn straight by `mark: "geoshape"`, with no converter node; polygons plus a second `centroid` geometry column | Chicago ZIP boundaries | 🟢 |
| 13 | [Vega-Lite geometry columns](examples/13-vega-lite-geometry-columns.md) | Which column holds the geometry: renamed columns, several at once, none at all, and the two states where the node refuses to guess | Chicago ZIP boundaries | 🟡 |
| 14 | [Vega-Lite CRS and geometry types](examples/14-vega-lite-crs-and-geometry-types.md) | The same spec over any coordinate system and any geometry type, including derived columns, empty frames and missing geometry | Chicago ZIP boundaries | 🟡 |
| 15 | [Vega-Lite spec forms and catalogs](examples/15-vega-lite-spec-forms-and-catalogs.md) | Writing the shape encoding and projection yourself, across layered and side-by-side maps, over geojson, GeoParquet and the output of the Spatial Join node | Chicago green roofs and sidewalk labels | 🟡 |
| 16 | [Simple View: tables and images](examples/16-simple-view-tables-and-images.md) | Two paths into `Simple View`: a plain frame renders as a table, a frame with two generated image columns renders as a card per row | Synthetic aerial tiles, self-generating | 🟢 |
| 17 | [Autark GeoDataFrame maps](examples/17-autark-geodataframe-maps.md) | The Autark node beside the Vega-Lite node on the same inputs: a GeoDataFrame, a DataFrame with and without a geometry column, a projected CRS, two layers from one node, and a chart linked to a map | Downtown Chicago ZIP polygons | 🟡 |
| 18 | [Storage: orthorectified imagery](examples/18-storage-orthorectified-imagery.md) | A folder of GeoTIFF tiles by year as one collection: footprints on a Vega-Lite map, then one year's tiles through `Mosaic Rasters` into a band summary | Drone tiles over the Chicago Loop | 🟡 |
| 19 | [Storage: video frames](examples/19-storage-video-frames.md) | A folder of numbered frames with a telemetry file as one collection: `Simple View` shows them in order, Vega-Lite draws each sequence as a track | Dashcam trips in the Chicago Loop | 🟢 |
| 20 | [Storage: a folder of CSV files](examples/20-storage-folder-of-csv-files.md) | One CSV per sensor and day combined into one table, charted over time, then joined to a stations file through `Merge Flow` and mapped | Air quality sensors in the Chicago Loop | 🟢 |
| 21 | [Storage: photos and videos](examples/21-storage-photos-and-videos.md) | Geotagged photos and a video as one collection: a `Simple View` gallery that plays the video, a map, and `Sample Video Frames` | A street survey in the Chicago Loop | 🟡 |
| 22 | [Storage: audio recordings](examples/22-storage-audio-recordings.md) | Recordings timed by their file names as one collection: spectrogram cards, then `Split Audio` levels per window in Vega-Lite | Noise sensors in the Chicago Loop | 🟡 |
| 23 | [Storage: a folder of different files](examples/23-storage-folder-of-different-files.md) | A shapefile and a GeoJSON file from one folder, each its own dataset, stacked on one Vega-Lite map | Roads and a park in the Chicago Loop | 🟢 |
