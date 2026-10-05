# Worked examples

This file indexes the dataflows Curio ships, for the built-in agents. A run of an agent that takes worked examples gets the "Used" dataflows that best match its task, each as its line below and its Trill. Every shipped dataflow is listed in exactly one section. A line says what its dataflow shows; the name, task, city, topic, node types and datasets are read from the file itself.

## Used

- [Vega-Lite chained transforms](../../docs/examples/01-vega-lite-chained-transforms.json): Crowdsourced sidewalk accessibility labels cleaned in three chained pandas steps (an agreement ratio, severity bins, counts per feature type and per neighborhood), then a bar chart of features by type coloured by severity and a dot plot of features per neighborhood.
- [Vega-Lite spatial density](../../docs/examples/02-vega-lite-spatial-density.json): Green roof permits turned into points and joined to ZIP code polygons; one load fans out to a log-scaled histogram of roof sizes, a point map of roof locations and a bar chart of the ten ZIP codes with the most vegetated roof area.
- [Vega-Lite linked temporal charts](../../docs/examples/03-vega-lite-linked-temporal-charts.json): Speed camera violations summed per camera and year for the busiest cameras, shown as a bar chart of yearly totals beside a line chart of the overall trend.
- [Vega-Lite multi-flow dashboard](../../docs/examples/04-vega-lite-multi-flow-dashboard.json): Red light camera violations cleaned along several independent branches that are joined and aggregated into a dashboard: a daily seasonal trend line, a seasonal area chart over time, a bar chart of the top intersections per year, and more summary charts.
- [Vega-Lite multi-view drilldown](../../docs/examples/05-vega-lite-multi-view-drilldown.json): Building electricity and gas benchmarks split into five parallel branches: a consumption heatmap, a dot plot by building type, a bar chart of the top ten community areas, a log-scale scatter of electricity against gas, and a strip plot of gas use.
- [Autark what-if shadow study](../../docs/examples/06-autark-what-if-shadow-study.json): A what-if shadow study on OpenStreetMap buildings and roads: a GPU shader adds up each road's minutes of June solstice sunlight under the real building heights, a second run doubles every height, and two maps side by side show the sunlight lost.
- [Autark GPU shader](../../docs/examples/07-autark-gpu-shader.json): A WGSL compute shader run on the GPU over OpenStreetMap roads and buildings, giving each road the minutes of June solstice sunlight that no building blocks; a 3D map coloured by sunlight linked to a brushable histogram.
- [Autark spatial join + regression](../../docs/examples/08-autark-spatial-join-regression.json): OpenStreetMap roads joined to 24 years of land surface temperature from a GeoTIFF in a JavaScript node, a per-road least squares warming trend fitted on the GPU, and a 3D map linked to a brushable scatter of warming against baseline temperature.
- [Heterogeneous data + linked views](../../docs/examples/09-heterogeneous-data-linked-views.json): Thermal comfort (UTCI) computed from a mean radiant temperature raster and hourly weather readings, averaged per census tract and set against the share of residents over 65; a choropleth map and a scatter plot brushed together, plus a box plot.
- [Street-level computer vision](../../docs/examples/10-street-vision-cv-analysis.json): Street photos labelled pixel by pixel by a shipped segmentation model and by a Hugging Face model, cards of each photo beside its overlay, each photo tagged with the neighborhood it falls in, then a map of neighborhoods by dominant class and bar charts of photo counts.
- [Autark PBF loading](../../docs/examples/11-autark-pbf-loading.json): OpenStreetMap layers parsed in the browser from a local .pbf file and drawn as a map with buildings coloured by height, linked to a brushable height histogram.
- [Vega-Lite GeoDataFrame maps](../../docs/examples/12-vega-lite-geodataframe-maps.json): A GeoDataFrame of ZIP code polygons drawn straight from a geoshape mark, its centroids as a second geometry layer, and bar and scatter charts over the same frame.
- [Vega-Lite geometry columns](../../docs/examples/13-vega-lite-geometry-columns.json): How a map finds its geometry: an active geometry column with another name, several geometry columns in one frame, shapely objects in a plain DataFrame, and frames with no geometry, each drawn as a geoshape map or a bar chart.
- [Vega-Lite CRS and geometry types](../../docs/examples/14-vega-lite-crs-and-geometry-types.json): One geoshape spec over any coordinate system and geometry type: bounding boxes, projected metres, mixed geometry types in one column, an empty frame, all-null geometry, a geographic CRS other than 4326, and a frame with no CRS.
- [Vega-Lite spec forms and catalogs](../../docs/examples/15-vega-lite-spec-forms-and-catalogs.json): Hand-written map specs (explicit shape encodings, a custom projection, layered and side-by-side maps) over three catalog file formats, and roof points counted per ZIP polygon, drawn as a choropleth and as bars.
- [Simple View: tables and images](../../docs/examples/16-simple-view-tables-and-images.json): A plain frame of readings shown as a table, and a frame with two image columns (tiles and their vegetation masks as data: URIs) shown as cards.
- [Autark GeoDataFrame maps](../../docs/examples/17-autark-geodataframe-maps.json): ZIP code polygons drawn by both map grammars side by side from the same frames (a GeoDataFrame, one geometry column, none, a projected CRS), and a bar chart of area by ZIP linked to the map on hover.
- [Storage: orthorectified imagery](../../docs/examples/18-storage-orthorectified-imagery.json): A folder of aerial GeoTIFF tiles indexed as one collection: tile footprints mapped per year flown, one year's tiles kept and joined into one raster, and its band statistics shown as a table.
- [Storage: video frames](../../docs/examples/19-storage-video-frames.json): Numbered dashcam frames with a telemetry file, indexed as one collection: the frames shown in order as cards, and each sequence drawn as a track on a map.
- [Storage: a folder of CSV files](../../docs/examples/20-storage-folder-of-csv-files.json): Air quality readings combined from one CSV file per sensor and day: a PM2.5 line chart per sensor, then each sensor's mean joined to its station and mapped as sized circles.
- [Storage: photos and videos](../../docs/examples/21-storage-photos-and-videos.json): A street survey folder of geotagged photos and a video: every file as a card (the video plays in its card), a map of where each was taken, and frames sampled from the video every quarter second.
- [Storage: audio recordings](../../docs/examples/22-storage-audio-recordings.json): Noise recordings per sensor, timed by their file names: a spectrogram card for each recording, then the recordings cut into 0.1 second windows and each window's level charted per sensor.
- [Storage: a folder of different files](../../docs/examples/23-storage-folder-of-different-files.json): A roads shapefile and a parks GeoJSON file from one folder, each added as its own dataset, stacked into one GeoDataFrame and drawn on one map.
- [DataPool_Vega_2](../../docs/examples/dataflows/DataPool_Vega_2.json): Green roof permits joined to ZIP code polygons, the ten ZIP codes with the most vegetated roof area kept, and a bar chart with a point selection over them.
- [Interaction_Autark](../../docs/examples/dataflows/Interaction_Autark.json): OpenStreetMap buildings loaded from a .pbf file, missing heights filled on the GPU, and a map coloured by height linked both ways to a brushable height histogram.
- [Regression](../../docs/examples/dataflows/Regression.json): OpenStreetMap roads joined to nearby surface polygons, lane counts clamped on the GPU, and a map of roads coloured by lanes linked both ways to a brushable lane histogram.

## Not used

- [AutkMap](../../docs/examples/dataflows/AutkMap.json): checks that a map draws a GeoDataFrame from its input, on three squares built in code.
- [BuildingRasters](../../docs/examples/dataflows/BuildingRasters.json): checks SCOUT's building rasterizer package and a map of its height mosaic, on four buildings built in code.
- [DataPool_AutkMap](../../docs/examples/dataflows/DataPool_AutkMap.json): the same check through a pool node, on squares built in code.
- [DataPool_Dataframe](../../docs/examples/dataflows/DataPool_Dataframe.json): checks the pool grid on a hand-typed nine-row frame.
- [DataPool_Geodataframe](../../docs/examples/dataflows/DataPool_Geodataframe.json): checks the pool grid on geometry, read from a repository file by path instead of a catalog dataset.
- [DataPool_Vega](../../docs/examples/dataflows/DataPool_Vega.json): checks a chart fed through a pool, on a hand-typed frame.
- [DefaultWorkflow](../../docs/examples/dataflows/DefaultWorkflow.json): the starter canvas, random numbers and their median.
- [Image](../../docs/examples/dataflows/Image.json): checks image rendering, from a repository folder read by path.
- [Simple View images](../../docs/examples/dataflows/ImageUrls.json): checks that image columns render as cards, which example 16 shows in full.
- [Interaction_AutkMap](../../docs/examples/dataflows/Interaction_AutkMap.json): checks a selection from a pool to a map, on squares built in code.
- [Interaction_Vega](../../docs/examples/dataflows/Interaction_Vega.json): checks brushing from a chart through a pool, on a repository file read by path instead of a catalog dataset.
- [Interaction_Vega_Autark](../../docs/examples/dataflows/Interaction_Vega_Autark.json): checks brushing between a chart and a map through a pool, on a repository file read by path instead of a catalog dataset.
- [Interaction_Vega_Simple](../../docs/examples/dataflows/Interaction_Vega_Simple.json): checks a point selection on a five-row hand-typed frame.
- [JSComputation](../../docs/examples/dataflows/JSComputation.json): checks the JavaScript runner on a list of three numbers.
- [MultiInput](../../docs/examples/dataflows/MultiInput.json): checks the input order of a node with two inputs, on two hand-typed frames.
- [MultiInputDataPool](../../docs/examples/dataflows/MultiInputDataPool.json): checks a pool with five inputs, on hand-typed frames.
- [SimpleView](../../docs/examples/dataflows/SimpleView.json): checks the table view on a three-row hand-typed frame.
- [Vega](../../docs/examples/dataflows/Vega.json): checks the chart renderer on a hand-typed bar chart.
- [Widget](../../docs/examples/dataflows/Widget.json): checks the widget input syntax in node code.
