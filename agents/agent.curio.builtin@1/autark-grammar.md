# Autark grammar

The words of the `autark` skill's section on Autark documents, which the
prompt field `autk.grammar` puts in place. The runtime fills each `{name}` from the
vendored Autark schema
when it renders the section: the template's label and id, the schema's id, the
families a document names, what each part requires, and the schema's own
descriptions. One section per line of the section, by the name the runtime
reads it by; the runtime writes the list marks before each and the lines of
the schema's own choices between them. A section `source-<type>` ends the
line of the data source of that `type`, each `{name}` in it the schema's
words on one of that source's fields.

## intro

{label} nodes ({template}) are controlled through grammar: their content is one JSON document that follows the Autark grammar's JSON Schema ({schema_id}). Keys the schema does not name are allowed. A document names at least one of {families}.

## inputs

In the document, the node's inputs are the layers named "{first}", "{second}", ... in the order of its input circles; the layers an upstream {label} node produces keep their table names, such as "table_osm_buildings". The document writes no "data" entry for its inputs. An input of several layers is named one layer at a time, by a layer chip such as "{{inputs.chip:0:table_osm_buildings}}": its input chip is refused. A raster input is drawn on a map by one band, "getFnv": "band_1", "band_2" and so on, and so are a "geotiff" the document's "data" loads and a "heatmap" it builds, whose bands are also named by their aggregate and table ("count.noise" counts the rows of the table "noise"). A "geotiff" names its file by its path from the folder Curio was started from, as "pbfFileUrl" does, or by a URL. A "heatmap" bins, and a "join" reads, a table the document's own "data" loads before it, or a table of the node's input, named as above ("{first}", or a layer's own name), which the node loads into the entry's workspace and does not hand on again unless a "join" wrote its columns onto it; a heatmap's "near.distance" is in the map's planar units (EPSG:3395), about three quarters of a meter on the ground at Chicago, and each "groupBy" entry is a band that counts the rows near a cell ("count", or "weighted" by 1 / (distance + 1)) or aggregates their "column" ("sum", "avg", "min", "max"); "normalize": true rescales a band from 0 to 1 across the grid's cells and ends its name in "_norm" ("count.noise_norm"), and bands of one aggregate over different columns add their column ("avg.noise.db"). An "update" and a "drop" read a table of the node's input as a "join" does, and the node hands on a table an "update" changed; a "sql" query reads the tables the document's own "data" loads before it. No compute pass reads a raster: compute over a raster's cells in a Python node. "selectFields" reads a table from the node's input and names columns some feature of it holds, or the run fails.

## data

"data": {description} Each entry's "type" selects its fields:

## requires

Requires {fields}.

## source-osm

Its "tagSets": {tag_sets} Each set is written as {"name": "cafes", "type": "points", "tags": [{"key": "amenity", "value": "cafe"}]}, and a tag without a "value" matches its key with any value. Its "forceRefresh": {force_refresh} Its "autoLoadLayers" also takes "coordinateFormat": {coordinate_format}

## source-sql

Its "query": {query} Its "layerType": {layer_type}

## source-update

Its "strategy": {strategy} The rows go in "geojsonObject" or "jsonObject", and its "idColumn": {id_column}

## compute

"compute": {description} {pass_description} A GPGPU pass also requires {fields}.

## uniform

A uniform is written inline or as {"fromFeature": {...}}. {directive} Its "iterate": {iterate}

## render

"type": "render": {description} It requires {fields}.

## render-layers

Each entry of its "layers" requires {layer_fields}, with a "type" of {layer_types}, and its "viewpoints" requires {viewpoint_fields}.

## views

A node draws every map and plot of its document, each in a pane of its own: the maps in the order of "map", then the plots in the order of "plot", arranged by "layout" and stacked without it. An "id" names a map or a plot and is unique among them: a link in "links" names a plot by its "id" (else its "dataRef") and a map by its "id", and two plots of one table each need an "id". In a node of several views, each view with an "id" has an interaction dot of its own, which a plan's interaction edge names with "fromView" or "toView".

## map

"map": {description} Requires {map_fields}, and each entry of "{layers}" requires {layer_fields}. "colorMapInterpolator" is one of {interpolators}. A layer that shows a legend names it with "title": {layer_title}

## plot

"plot": {description} Every plot requires {plot_fields}; "mark" selects the rest:

## plot-keys

Every mark takes these: "color" names the column its marks are colored by. Numbers take "colorMapInterpolator", a sequential or diverging "interpolate" scheme of the map's list, from the lowest value to the highest, or over "colorMapRange" ([low, high]), or between percentiles with "normalization" ({"mode": "percentile", "lowerPercentile": 5, "upperPercentile": 95}). Categories take "categoricalColorMapInterpolator", a "scheme" of that list, in the order of "colorMapDomain" when it is given. "tickFormats" holds the d3-format specifiers of the x and y tick labels, such as [",d", ".1f"]; "axisLabels" titles the axes in the order of "axis"; "selection" lists the rows drawn selected, by their positions among the rows the plot draws, from 0. "markColor" and "highlightColor", as "#rrggbb", color the marks no value colors and the selected ones. autk-plot keeps one of each for the whole page, for every plot of every node, and each node's run sets them, back to autk-plot's own when its plots set none: give every plot of a dataflow the same "markColor" and "highlightColor", or none.

## elements

A map layer's or a plot's "osmElements": {elements} It reads a table the document's own "osm" source loads; a table of the node's input is drawn row by row. The views of one node that read the same table all write "osmElements": true, or none does.
