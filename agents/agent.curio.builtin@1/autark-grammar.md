# Autark grammar

The words of the preamble's section on Autark documents, which the prompt
field `autk.grammar` puts in place. The runtime fills each `{name}` from the
vendored Autark schema
when it renders the section: the template's label and id, the schema's id, the
families a document names, what each part requires, and the schema's own
descriptions. One section per line of the section, by the name the runtime
reads it by; the runtime writes the list marks before each and the lines of
the schema's own choices between them.

## intro

{label} nodes ({template}) are controlled through grammar: their content is one JSON document that follows the Autark grammar's JSON Schema ({schema_id}). Keys the schema does not name are allowed. A document names at least one of {families}.

## inputs

In the document, the node's inputs are the layers named "{first}", "{second}", ... in the order of its input circles; the layers an upstream {label} node produces keep their table names, such as "table_osm_buildings". The document writes no "data" entry for its inputs.

## data

"data": {description} Each entry's "type" selects its fields:

## requires

Requires {fields}.

## compute

"compute": {description} {pass_description} Every pass also requires {fields}.

## uniform

A uniform is written inline or as {"fromFeature": {...}}. {directive} Its "iterate": {iterate}

## map

"map": {one_view} Requires {map_fields}, and each entry of "{layers}" requires {layer_fields}. "colorMapInterpolator" is one of {interpolators}. A layer that shows a legend names it with "title": {layer_title}

## plot

"plot": {one_view} Every plot requires {plot_fields}; "mark" selects the rest:
