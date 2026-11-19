# Autark grammar

The words of the `autark` skill's section on Autark documents, which the
prompt field `autk.grammar` puts in place. The runtime fills each `{name}` from the
vendored Autark schema
when it renders the section: the template's label and id, the schema's id, the
families a document names, what each part requires, and the schema's own
descriptions. One section per line of the section, by the name the runtime
reads it by; the runtime writes the list marks before each and the lines of
the schema's own choices between them.

## intro

{label} nodes ({template}) are controlled through grammar: their content is one JSON document that follows the Autark grammar's JSON Schema ({schema_id}). Keys the schema does not name are allowed. A document names at least one of {families}.

## inputs

In the document, the node's inputs are the layers named "{first}", "{second}", ... in the order of its input circles; the layers an upstream {label} node produces keep their table names, such as "table_osm_buildings". The document writes no "data" entry for its inputs. An input of several layers is named one layer at a time, by a layer chip such as "{{inputs.chip:0:table_osm_buildings}}": its input chip is refused. A raster input is drawn on a map by one band, "getFnv": "band_1", "band_2" and so on, and so are a "geotiff" the document's "data" loads and a "heatmap" it builds, whose bands are also named by their aggregate and table ("count.noise" counts the rows of the table "noise"). A "geotiff" names its file by its path from the folder Curio was started from, as "pbfFileUrl" does, or by a URL. A "heatmap" bins, and a "join" reads, a table the document's own "data" loads before it, or a table of the node's input, named as above ("{first}", or a layer's own name), which the node loads into the entry's workspace and does not hand on again unless a "join" wrote its columns onto it; a heatmap's "near.distance" is in the map's planar units (EPSG:3395), about three quarters of a meter on the ground at Chicago, and each "groupBy" entry is a band that counts the rows near a cell ("count", or "weighted" by 1 / (distance + 1)) or aggregates their "column" ("sum", "avg", "min", "max"); a normalized band's name ends in "_norm" ("count.noise_norm"), and bands of one aggregate over different columns add their column ("avg.noise.db"). No compute pass reads a raster: compute over a raster's cells in a Python node. "selectFields" reads a table from the node's input and names columns some feature of it holds, or the run fails.

## data

"data": {description} Each entry's "type" selects its fields:

## requires

Requires {fields}.

## compute

"compute": {description} {pass_description} A GPGPU pass also requires {fields}.

## uniform

A uniform is written inline or as {"fromFeature": {...}}. {directive} Its "iterate": {iterate}

## render

"type": "render": {description} It requires {fields}.

## render-layers

Each entry of its "layers" requires {layer_fields}, with a "type" of {layer_types}, and its "viewpoints" requires {viewpoint_fields}.

## views

A node draws every map and plot of its document, each in a pane of its own: the maps in the order of "map", then the plots in the order of "plot", arranged by "layout" and stacked without it. An "id" names a map or a plot and is unique among them: a link in "links" names a plot by its "id" (else its "dataRef") and a map by its "id", and two plots of one table each need an "id".

## map

"map": {description} Requires {map_fields}, and each entry of "{layers}" requires {layer_fields}. "colorMapInterpolator" is one of {interpolators}. A layer that shows a legend names it with "title": {layer_title}

## plot

"plot": {description} Every plot requires {plot_fields}; "mark" selects the rest:
